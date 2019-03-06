import unittest
from inferelator_ng.postprocessing import results_processor
import pandas as pd
import numpy as np
import os

class TestResultsProcessor(unittest.TestCase):

    def test_full_stack(self):
        beta = pd.DataFrame(np.array([[0, 1], [0.5, 0.05]]), ['gene1', 'gene2'], ['tf1', 'tf2'])
        beta_resc = pd.DataFrame(np.array([[0, 1], [1, 0.05]]), ['gene1', 'gene2'], ['tf1', 'tf2'])
        prior = pd.DataFrame([[0, 1], [1, 0]], ['gene1', 'gene2'], ['tf1', 'tf2'])
        gold_standard = pd.DataFrame([[0, 1], [1, 0]], ['gene1', 'gene2'], ['tf1', 'tf2'])
        rp = results_processor.ResultsProcessor([beta], [beta_resc])
        aupr = rp.summarize_network(None, gold_standard, prior)
        self.assertEqual(aupr, 1)

    def test_combining_confidences_one_beta(self):
        # rescaled betas are only in the 
        beta = pd.DataFrame(np.array([[0.5, 0], [0.5, 1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = results_processor.RankSummaryPR.compute_combined_confidences([beta])
        np.testing.assert_equal(confidences.values,
            np.array([[0.5,  0.0], [0.5,      1.0]]))

    def test_combining_confidences_one_beta_invariant_to_rescale_division(self):
        # rescaled betas are only in the 
        beta = pd.DataFrame(np.array([[1, 0], [1, 2]]), ['gene1', 'gene2'], ['tf1','tf2'])
        rescaled_beta = pd.DataFrame((beta / 3.0), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = results_processor.RankSummaryPR.compute_combined_confidences([rescaled_beta])
        np.testing.assert_equal(confidences.values,
            np.array([[0.5,  0.0], [0.5,      1.0]]))

    def test_combining_confidences_one_beta_all_negative_values(self):
        # rescaled betas are only in the 
        beta = pd.DataFrame(np.array([[-1, -.5, -3], [-1, -2, 0]]), ['gene1', 'gene2'], ['tf1','tf2', 'tf3'])
        rescaled_beta = pd.DataFrame([[0.2, 0.1, 0.4], [0.3, 0.5, 0]], ['gene1', 'gene2'], ['tf1','tf2', 'tf3'])
        confidences = results_processor.RankSummaryPR.compute_combined_confidences([rescaled_beta])
        np.testing.assert_equal(confidences.values,
            np.array([[0.4, 0.2, 0.8], [0.6,  1.0, 0]]))

    def test_combining_confidences_one_beta_with_negative_values(self):
        # data was taken from a subset of row 42 of b subtilis run
        beta = pd.DataFrame(np.array([[-0.2841755, 0, 0.2280624, -0.3852462, 0.2545609]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        rescaled_beta = pd.DataFrame(np.array([[0.09488207, 0, 0.07380172, 0.15597205, 0.07595131]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        confidences = results_processor.RankSummaryPR.compute_combined_confidences([rescaled_beta])
        np.testing.assert_equal(confidences.values,
            np.array([[ 0.75,  0,  0.25,  1,  0.5 ]]))

    def test_combining_confidences_two_betas_negative_values(self):
        # data was taken from a subset of row 42 of b subtilis run
        beta1 = pd.DataFrame(np.array([[-0.2841755, 0, 0.2280624, -0.3852462, 0.2545609]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        rescaled_beta1 = pd.DataFrame(np.array([[0.09488207, 0, 0.07380172, 0.15597205, 0.07595131]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        beta2 = pd.DataFrame(np.array([[0, 0.2612011, 0.1922999, 0.00000000, 0.19183277]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        rescaled_beta2 = pd.DataFrame(np.array([[0, 0.09109101, 0.05830292, 0.00000000, 0.3675702]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        confidences = results_processor.RankSummaryPR.compute_combined_confidences([rescaled_beta1, rescaled_beta2])
        np.testing.assert_equal(confidences.values,
            np.array([[ 0.1,  0. ,  0. ,  0.3,  0.6]]))

    def test_combining_confidences_two_betas_negative_values_assert_nonzero_betas(self):
        # data was taken from a subset of row 42 of b subtilis run
        beta1 = pd.DataFrame(np.array([[-0.2841755, 0, 0.2280624, -0.3852462, 0.2545609]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        rescaled_beta1 = pd.DataFrame(np.array([[0.09488207, 0, 0.07380172, 0.15597205, 0.07595131]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        beta2 = pd.DataFrame(np.array([[0, 0.2612011, 0.1922999, 0.00000000, 0.19183277]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        rescaled_beta2 = pd.DataFrame(np.array([[0, 0.09109101, 0.05830292, 0.00000000, 0.3675702]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        _, _, betas_non_zero = results_processor.ResultsProcessor.threshold_and_summarize([beta1, beta2], 0.5)
        np.testing.assert_equal(betas_non_zero, np.array([[1 ,1, 2, 1, 2]]))

    def test_combining_confidences_two_betas_negative_values_assert_sign_betas(self):
        # data was taken from a subset of row 42 of b subtilis run
        beta1 = pd.DataFrame(np.array([[-0.2841755, 0, 0.2280624, -0.3852462, 0.2545609]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        rescaled_beta1 = pd.DataFrame(np.array([[0.09488207, 0, 0.07380172, 0.15597205, 0.07595131]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        beta2 = pd.DataFrame(np.array([[0, 0.2612011, 0.1922999, 0.00000000, 0.19183277]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        rescaled_beta2 = pd.DataFrame(np.array([[0, 0.09109101, 0.05830292, 0.00000000, 0.3675702]]), ['gene1'], ['tf1','tf2','tf3', 'tf4', 'tf5'])
        _, betas_sign, _ = results_processor.ResultsProcessor.threshold_and_summarize([beta1, beta2], 0.5)
        np.testing.assert_equal(betas_sign, np.array([[-1 ,1, 2, -1, 2]]))


    def test_threshold_and_summarize_one_beta(self):
        beta1 = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        thresholded_mat, _, _ = results_processor.ResultsProcessor.threshold_and_summarize([beta1], 0.5)
        np.testing.assert_equal(thresholded_mat.values,
            np.array([[1,0],[1,0]]))

    def test_threshold_and_summarize_two_betas(self):
        beta1 = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        beta2 = pd.DataFrame(np.array([[0, 0], [0.5, 1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        thresholded_mat, _, _ = results_processor.ResultsProcessor.threshold_and_summarize([beta1, beta2], 0.5)
        np.testing.assert_equal(thresholded_mat.values,
            np.array([[1,0],[1,1]]))

    def test_threshold_and_summarize_three_betas(self):
        beta1 = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        beta2 = pd.DataFrame(np.array([[0, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        beta3 = pd.DataFrame(np.array([[0.5, 0.2], [0.5, 0.1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        thresholded_mat, _, _ = results_processor.ResultsProcessor.threshold_and_summarize([beta1, beta2, beta3], 0.5)
        np.testing.assert_equal(thresholded_mat.values,
            np.array([[1,0],[1,0]]))

    def test_threshold_and_summarize_three_betas_negative_values(self):
        beta1 = pd.DataFrame(np.array([[1, 0], [-0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        beta2 = pd.DataFrame(np.array([[0, 0], [-0.5, 1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        beta3 = pd.DataFrame(np.array([[-0.5, 0.2], [-0.5, 0.1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        thresholded_mat, _, _ = results_processor.ResultsProcessor.threshold_and_summarize([beta1, beta2, beta3], 0.5)
        np.testing.assert_equal(thresholded_mat.values,
            np.array([[1,0],[1,1]]))


####################

# TODO: Fix the following three tests so that they have unique and correct precision recall values

####################

    def test_precision_recall_perfect_prediction(self):
        gs = pd.DataFrame(np.array([[1, 0], [1, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        recall, precision = results_processor.RankSummaryPR.modify_pr(recall, precision)
        np.testing.assert_equal(recall, [ 0., 0.5, 1., 1., 1.])
        np.testing.assert_equal(precision, [ 1., 1., 1., 2./3, 0.5])

    def test_precision_recall_prediction_off(self):
        gs = pd.DataFrame(np.array([[1, 0], [0, 1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        recall, precision = results_processor.RankSummaryPR.modify_pr(recall, precision)
        np.testing.assert_equal(recall, [ 0.,   0.5, 0.5, 1., 1. ])
        np.testing.assert_equal(precision, [ 1.,  1., 0.5, 2./3, 0.5])

    def test_precision_recall_bad_prediction(self):
        gs = pd.DataFrame(np.array([[0, 1], [1, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0, 0.5]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        recall, precision = results_processor.RankSummaryPR.modify_pr(recall, precision)
        np.testing.assert_equal(recall, [ 0., 0., 0.,  0.5,  1. ])
        np.testing.assert_equal(precision, [ 0., 0., 0., 1./3, 0.5,])

    def test_aupr_perfect_prediction(self):
        gs = pd.DataFrame(np.array([[1, 0], [1, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        aupr = results_processor.RankSummaryPR.calculate_aupr(recall, precision)
        np.testing.assert_equal(aupr, 1.0)

    def test_negative_gs_aupr_perfect_prediction(self):
        gs = pd.DataFrame(np.array([[-1, 0], [-1, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        aupr = results_processor.RankSummaryPR.calculate_aupr(recall, precision)
        np.testing.assert_equal(aupr, 1.0)

    def test_negative_gs_precision_recall_bad_prediction(self):
        gs = pd.DataFrame(np.array([[0, -1], [-1, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0, 0.5]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        recall, precision = results_processor.RankSummaryPR.modify_pr(recall, precision)
        np.testing.assert_equal(recall, [ 0., 0., 0.,  0.5,  1. ])
        np.testing.assert_equal(precision, [ 0., 0., 0., 1./3, 0.5,])

    def test_aupr_prediction_off(self):
        gs = pd.DataFrame(np.array([[1, 0], [0, 1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0.5, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        aupr = results_processor.RankSummaryPR.calculate_aupr(recall, precision)
        np.testing.assert_equal(aupr, 19./24)

    def test_aupr_bad_prediction(self):
        gs = pd.DataFrame(np.array([[0, 1], [1, 0]]), ['gene1', 'gene2'], ['tf1','tf2'])
        confidences = pd.DataFrame(np.array([[1, 0], [0, 0.5]]), ['gene1', 'gene2'], ['tf1','tf2'])
        recall, precision, _ = results_processor.RankSummaryPR.calculate_precision_recall(confidences, gs)
        aupr = results_processor.RankSummaryPR.calculate_aupr(recall, precision)
        np.testing.assert_approx_equal(aupr, 7./24)

    def test_mean_and_median(self):
        beta1 = pd.DataFrame(np.array([[1, 1], [1, 1]]), ['gene1', 'gene2'], ['tf1','tf2'])
        beta2 = pd.DataFrame(np.array([[2, 2], [2, 2]]), ['gene1', 'gene2'], ['tf1','tf2'])
        mean, median = results_processor.ResultsProcessor.mean_and_median([beta1, beta2])
        np.testing.assert_equal(mean, np.array([[ 1.5,  1.5],[ 1.5,  1.5]]))
        np.testing.assert_equal(median, np.array([[ 1.5, 1.5],[ 1.5, 1.5]]))

    def test_plot_pr_curve(self):
        file_name = "/tmp/pr_curve.pdf"
        if os.path.exists(file_name):
            os.remove(file_name)
        results_processor.RankSummaryPR.plot_pr_curve([0, 1], [1, 0], "x", "/tmp", "pr_curve.pdf")
        exists = os.path.exists(file_name)
        self.assertTrue(exists)

    def test_plot_pr_curve_file_name(self):
        results_processor.RankSummaryPR.plot_pr_curve(recall=0.7, precision=0.5, aupr=0.9, output_dir="/tmp", file_name="pr_curve.pdf")

    def test_plot_pr_curve_file_name_none(self):
        results_processor.RankSummaryPR.plot_pr_curve(recall=0.3, precision=0.5, aupr=0.6, output_dir=None, file_name=None)
        