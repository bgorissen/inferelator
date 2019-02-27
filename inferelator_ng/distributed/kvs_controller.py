"""
KVSController is a wrapper for KVSClient that adds some useful functionality related to interprocess
communication.
It also keeps track of a bunch of SLURM related stuff that was previously workflow's problem.
"""

from kvsstcp import KVSClient

from inferelator_ng.utils import Validator as check

import os
import warnings
import collections
import itertools
import tempfile
import pickle

# SLURM environment variables
SBATCH_VARS = dict(SLURM_PROCID=('rank', int, 0),
                   SLURM_NTASKS_PER_NODE=('cores', int, 1),
                   SLURM_NTASKS=('tasks', int, 1),
                   SLURM_NODEID=('node', int, 0),
                   SLURM_JOB_NUM_NODES=('num_nodes', int, 1))

DEFAULT_MASTER = 0
DEFAULT_WARNING = "SBATCH has not set ENV {var}. Setting {var} to {defa}."

# KVS Keys to use

GET_COUNT = "kvs_get"
TMP_FILE_SYNC = "tmp_file_read"
POST_GET_SYNC = "post_get"
PILEUP_DATA = "data_pileup"
FINAL_DATA = "final_data"


class KVSController:
    # Set from SLURM environment variables

    kvs_client = None

    rank = None  # int
    tasks = None  # int
    node = None  # int
    cores = None  # int
    num_nodes = None  # int
    is_master = False  # bool

    @classmethod
    def connect(cls, *args, **kwargs):
        """
        Create a new KVS object with some object variables set to reflect the slurm environment
        """

        # Get local environment variables
        cls._get_env(suppress_warnings=kwargs.pop("suppress_warnings", False),
                     master_rank=kwargs.pop("master_rank", 0))

        # Connect to the host server by calling to KVSClient.__init__
        cls.kvs_client = KVSClient(*args, **kwargs)

    @classmethod
    def _get_env(cls, slurm_variables=SBATCH_VARS, suppress_warnings=False, master_rank=DEFAULT_MASTER):
        """
        Get the SLURM environment variables that are set by sbatch at runtime.
        The default values mean multiprocessing won't work at all.
        """
        for env_var, (class_var, func, default) in slurm_variables.items():
            try:
                val = func(os.environ[env_var])
            except (KeyError, TypeError):
                val = default
                if not suppress_warnings:
                    print(DEFAULT_WARNING.format(var=env_var, defa=default))
            setattr(cls, class_var, val)
        if cls.rank == master_rank:
            cls.is_master = True
        else:
            cls.is_master = False

    @classmethod
    def own_check(cls, chunk=1, kvs_key='count'):
        if cls.is_master:
            return ownCheck(cls.kvs_client, 0, chunk=chunk, kvs_key=kvs_key)
        else:
            return ownCheck(cls.kvs_client, 1, chunk=chunk, kvs_key=kvs_key)

    @classmethod
    def master_remove_key(cls, kvs_key='count'):
        if cls.is_master:
            cls.kvs_client.get(kvs_key)

    @classmethod
    def sync_processes(cls, pref="", value=True):
        """
        Block all processes until they reach this point, then release them
        It may be wise to use unique prefixes if this is gonna get called rapidly so there's no collision
        Or not. I'm a comment, not a cop.
        :param pref: str
            Prefix attached to the KVS keys
        :param value: Anything you can pickle
            A value that will be checked for consistency between processes (if you set a different value in a
            process, a warning will be issued. This is mostly to check state if needed
        :return None:
        """

        wkey = pref + '_wait'
        ckey = pref + '_continue'

        # Every process puts a wait key up when it gets here
        cls.put_key(wkey, value)

        # The master pulls down the wait keys until it has all of them
        # Then it puts up a go key for each process

        if cls.is_master:
            for _ in range(cls.tasks):
                c_value = cls.get_key(wkey)
                if c_value != value:
                    warnings.warn("Sync warning: master {val_m} is not equal to client {val_c}".format(val_m=value,
                                                                                                       val_c=c_value))
            for _ in range(cls.tasks):
                cls.put_key(ckey, True)

        # Every process waits here until go keys are available
        cls.get_key(ckey)

    @classmethod
    def get_key(cls, key):
        """
        Wrapper for KVSClient get
        """
        return cls.kvs_client.get(key)

    @classmethod
    def put_key(cls, key, value):
        """
        Wrapper for KVSClient put
        """
        return cls.kvs_client.put(key, value)

    @classmethod
    def view_key(cls, key):
        """
        Wrapper for KVSClient view
        """
        return cls.kvs_client.view(key)

    @classmethod
    def get(cls, dsk, result, chunk=25, tmp_file_path=None, tell_children=True):
        """
        Wrapper to handle multiprocessing data execution of very simple data pipelines
        Only one layer will be executed

        :param dsk: dict
            A dask graph {key: (func, arg1, arg2, ...)}
        :param result: key
            The result that we want
        :param chunk: int
            The number of iterations to assign in blocks.
        :param tmp_file_path: path
            If this is not None, instead of putting data onto the KVS, data will be pickled to temp files and the
            path to the temp file will be put onto the KVS
        :param tell_children: bool
            If this is True, all processes will end up with the final data after assembly. If false, only the master
            will have the final data; others will return None
        :return:
        """

        assert check.argument_type(result, collections.Hashable)
        assert check.argument_integer(chunk, low=1, allow_none=False)

        # If result points to a function tuple, start unpacking. Otherwise just return it
        if isinstance(dsk[result], tuple):
            func = dsk[result][0]
        else:
            return dsk[result]

        # If the function tuple is just a function, execute it and then return it
        if len(dsk[result]) == 1:
            return func()
        else:
            func_args = dsk[result][1:]

        # Unpack arguments and map anything that's got data in the graph
        map_args = []
        for arg in func_args:
            try:
                map_args.append(dsk[arg])
            except (TypeError, KeyError):
                map_args.append(arg)

        # Find out which arguments should be iterated over
        iter_args = [isinstance(arg, (tuple, list)) for arg in map_args]
        iter_product = []

        # If nothing is iterable, call the function and return it
        if sum(iter_args) == 0:
            return func(*map_args)

        # Put the iterables in a list
        for iter_bool, arg in zip(iter_args, map_args):
            if iter_bool:
                iter_product.append(arg)

        # Set up the multiprocessing
        owncheck = cls.own_check(chunk=chunk, kvs_key=GET_COUNT)
        results = dict()
        for pos, iterated_args in enumerate(itertools.product(*iter_product)):
            if next(owncheck):
                iter_arg_idx = 0
                current_args = []

                # Pack up this iteration's arguments into a list
                for iter_bool, arg in zip(iter_args, map_args):
                    if iter_bool:
                        current_args.append(iterated_args[iter_arg_idx])
                        iter_arg_idx += 1
                    else:
                        current_args.append(arg)

                # Run the function
                results[pos] = func(*current_args)

        # Process results and synchronize exit from the get call
        results = cls.process_results(results, tmp_file_path=tmp_file_path, tell_children=tell_children)
        cls.sync_processes(pref=POST_GET_SYNC)
        cls.master_remove_key(kvs_key=GET_COUNT)
        cls.master_remove_key(kvs_key=FINAL_DATA)
        return results

    @classmethod
    def process_results(cls, results, tmp_file_path=None, tell_children=True):
        """
        Pile up results from a get call
        :param results: dict
            A dict of results (keyed by position in a final list)
        :param tmp_file_path: path
            If this is not None, instead of putting data onto the KVS, data will be pickled to temp files and the
            path to the temp file will be put onto the KVS
        :param tell_children: bool
            If this is True, all processes will end up with the final data after assembly. If false, only the master
            will have the final data; others will return None
        :return: list
            A list of function results
        """

        if tmp_file_path is None:
            # Put the data in KVS
            cls.put_key(PILEUP_DATA, results)
        else:
            # Put the data in a pickled file
            temp_fd, temp_name = tempfile.mkstemp(prefix="kvs", dir=tmp_file_path)
            with os.fdopen(temp_fd, "wb") as temp:
                pickle.dump(results, temp, -1)
            cls.put_key(PILEUP_DATA, temp_name)

        if cls.is_master:
            # If this is the master thread, get all the data and pile it up
            pileup_results = dict()
            for _ in range(cls.tasks):
                if tmp_file_path is None:
                    pileup_results.update(cls.get_key(PILEUP_DATA))
                else:
                    temp_name = cls.get_key(PILEUP_DATA)
                    with open(temp_name, mode="r") as temp:
                        pileup_results.update(pickle.load(temp))
                    os.remove(temp_name)

            # Put everything into a list based on the dict key
            pileup_list = [None] * len(pileup_results)
            for idx, val in pileup_results.items():
                pileup_list[idx] = val

            if tell_children and tmp_file_path is None:
                # Put the piled-up data into KVS
                cls.put_key(FINAL_DATA, pileup_list)
            elif tell_children:
                # Pute the piled-up data into a pickled file
                temp_fd, temp_name = tempfile.mkstemp(prefix="kvs", dir=tmp_file_path)
                with os.fdopen(temp_fd, "wb") as temp:
                    pickle.dump(pileup_list, temp, -1)
                cls.put_key(FINAL_DATA, temp_name)
            else:
                # Put a None onto KVS - only the master needs this data
                cls.put_key(FINAL_DATA, None)

        else:
            # If this is not the master thread, get the finalized data when the master is finished
            if tell_children and tmp_file_path is None:
                pileup_list = cls.view_key(FINAL_DATA)
            elif tell_children:
                with open(cls.view_key(FINAL_DATA), "r") as temp:
                    pileup_list = pickle.load(temp)
            else:
                pileup_list = cls.view_key(FINAL_DATA)

        # Return the piled up data or wait until everyone is done so that the temp file can be deleted
        if tmp_file_path is None:
            return pileup_list
        else:
            cls.sync_processes(pref=TMP_FILE_SYNC)
            if cls.is_master:
                os.remove(cls.view_key(FINAL_DATA))
            return pileup_list


def ownCheck(kvs, rank, chunk=1, kvs_key='count'):
    """
    Generator
    :param kvs: KVSClient
        KVS object for server access
    :param chunk: int
        The size of the chunk given to each subprocess
    :param kvs_key: str
        The KVS key to increment (default is 'count')
    :yield: bool
        True if this process has dibs on whatever. False if some other process has claimed it first.
    """
    if rank == 0:
        kvs.put(kvs_key, 0)

    # Start at the baseline
    checks, lower, upper = 0, -1, -1

    while True:

        # Checks increments every loop
        # If it's greater than the upper bound, get a new lower bound from the KVS count
        # Set the new upper bound by adding chunk to lower
        # And then put the new upper bound back into KVS key

        if checks >= upper:
            lower = kvs.get(kvs_key)
            upper = lower + chunk
            kvs.put(kvs_key, upper)

        # Yield TRUE if this row belongs to this process and FALSE if it doesn't
        yield lower <= checks < upper
        checks += 1
