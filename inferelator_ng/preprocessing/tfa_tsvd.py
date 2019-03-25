from __future__ import division

import itertools
import numpy as np
import pandas as pd
from scipy import linalg
from sklearn.utils.extmath import randomized_svd

from inferelator_ng import utils
from inferelator_ng import default
from inferelator_ng.distributed.inferelator_mp import MPControl

DEFAULT_TSVD_POWER_NORMALIZER = "QR"

class TruncatedSVDTFA:
    """
    TFA calculates transcription factor activity using matrix pseudoinverse

        Parameters
    --------
    prior: pd.dataframe
        binary or numeric g by t matrix stating existence of gene-TF interactions.
        g: gene, t: TF.

    expression_matrix: pd.dataframe
        normalized expression g by c matrix. g--gene, c--conditions

    expression_matrix_halftau: pd.dataframe
        normalized expression matrix for time series.

    allow_self_interactions_for_duplicate_prior_columns=True: boolean
        If True, TFs that are identical to other columns in the prior matrix
        do not have their self-interactios removed from the prior
        and therefore will have the same activities as their duplicate tfs.
    """

    def __init__(self, prior, expression_matrix, expression_matrix_halftau):
        self.prior = prior
        self.expression_matrix = expression_matrix
        self.expression_matrix_halftau = expression_matrix_halftau

    def compute_transcription_factor_activity(self, allow_self_interactions_for_duplicate_prior_columns=True):
        # Find TFs that have non-zero columns in the priors matrix
        non_zero_tfs = pd.Index(self.prior.columns[(self.prior != 0).any(axis=0)])
        # Delete tfs that have neither prior information nor expression
        delete_tfs = self.prior.columns.difference(self.expression_matrix.index).difference(non_zero_tfs)

        # Raise warnings
        if len(delete_tfs) > 0:
            message = "{num} TFs are removed from activity (no expression or prior exists)".format(num=len(delete_tfs))
            utils.Debug.vprint(message, level=0)
            self.prior = self.prior.drop(delete_tfs, axis=1)

        # Create activity dataframe with values set by default to the transcription factor's expression
        # Create an empty dataframe [K x G]
        activity = pd.DataFrame(0.0, index=self.prior.columns, columns=self.expression_matrix.columns)

        # Populate with expression values as a default
        add_default_activity = self.prior.columns.intersection(self.expression_matrix.index)
        activity.loc[add_default_activity, :] = self.expression_matrix.loc[add_default_activity, :]

        # Find all non-zero TFs that are duplicates of any other non-zero tfs
        is_duplicated = self.prior[non_zero_tfs].transpose().duplicated(keep=False)

        # Find non-zero TFs that are also present in target gene list
        self_interacting_tfs = non_zero_tfs.intersection(self.prior.index)

        if is_duplicated.sum() > 0:
            duplicates = is_duplicated[is_duplicated].index.tolist()

            # If this flag is set to true, don't count duplicates as self-interacting when setting the diag to zero
            if allow_self_interactions_for_duplicate_prior_columns:
                self_interacting_tfs = self_interacting_tfs.difference(duplicates)

        # Set the diagonal of the matrix subset of self-interacting tfs to zero
        subset = self.prior.loc[self_interacting_tfs, self_interacting_tfs].values
        np.fill_diagonal(subset, 0)
        self.prior.at[self_interacting_tfs, self_interacting_tfs] = subset

        # Set the activity of non-zero tfs to the pseudoinverse of the prior matrix times the expression
        if len(non_zero_tfs) > 0:
            P = np.mat(self.prior[non_zero_tfs])
            X = np.matrix(self.expression_matrix_halftau)
            utils.Debug.vprint('Running TSVD...', level=1)
            k_val = gcv(P, X, 0)['val']
            utils.Debug.vprint('Selected {k} dimensions for TSVD'.format(k=k_val), level=1)
            A_k = tsvd_simple(P, X, k_val)
            activity.loc[non_zero_tfs, :] = np.matrix(A_k)

        return activity


def tsvd_simple(P, X, k, seed=default.DEFAULT_RANDOM_SEED, power_iteration_normalizer=DEFAULT_TSVD_POWER_NORMALIZER):
    U, Sigma, VT = randomized_svd(P, n_components=k, random_state=seed,
                                  power_iteration_normalizer=power_iteration_normalizer)
    Sigma_inv = [0 if s == 0 else 1. / s for s in Sigma]
    S_inv = np.diagflat(Sigma_inv)
    A_k = np.transpose(np.mat(VT)) * np.mat(S_inv) * np.transpose(np.mat(U)) * np.mat(X)
    return A_k


def gcv(P,X,biggest):
    #Make into a 'map' call so this is vectorized
    m = len(P)
    if biggest == 0:
        biggest = np.linalg.matrix_rank(P)

    if MPControl.name() == "dask":
        GCVect = gcv_dask(P, X, biggest, m)
    else:
        num_iter = biggest - 1
        GCVect = MPControl.map(calculate_gcval, itertools.repeat(P, num_iter), itertools.repeat(X, num_iter),
                               range(1, biggest), itertools.repeat(m, num_iter))

    GCVal = GCVect.index(min(GCVect)) + 1
    return {'val':GCVal,'vect':GCVect}


def calculate_gcval(P, X, k, m):
    utils.Debug.vprint("TSVD: {k} / {i}".format(k=k, i=min(P.shape)), level=2)
    A_k = tsvd_simple(P, X, k)
    Res = linalg.norm(P * A_k - X, 2)
    return (Res / (m - k)) ** 2


def gcv_dask(P, X, biggest, m):
    from dask import distributed
    DaskController = MPControl.client

    def gcv_maker(P, X, k, m):
        return k, calculate_gcval(P, X, k, m)

    [scatter_p] = DaskController.client.scatter([P], broadcast=True)
    [scatter_x] = DaskController.client.scatter([X], broadcast=True)
    future_list = [DaskController.client.submit(gcv_maker, scatter_p, scatter_x, i, m)
                   for i in range(1, biggest)]

    # Collect results as they finish instead of waiting for all workers to be done
    result_list = [None] * len(future_list)
    for finished_future, (j, result_data) in distributed.as_completed(future_list, with_results=True):
        result_list[j - 1] = result_data
        finished_future.cancel()

    DaskController.client.cancel(scatter_x)
    DaskController.client.cancel(scatter_p)
    DaskController.client.cancel(future_list)

    return result_list