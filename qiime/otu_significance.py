#!/usr/bin/env python
# File created on 13 Aug 2013
from __future__ import division

__author__ = "Will Van Treuren, Luke Ursell"
__copyright__ = "Copyright 2013, The QIIME project"
__credits__ = ["Will Van Treuren", "Luke Ursell", "Catherine Lozupone"]
__license__ = "GPL"
__version__ = "1.7.0-dev"
__maintainer__ = "Luke Ursell"
__email__ = "lkursell@gmail.com"
__status__ = "Development"

from biom.parse import parse_biom_table
from qiime.parse import parse_mapping_file_to_dict
from numpy import array, argsort, vstack, isnan, inf, nan
from qiime.pycogent_backports.test import (parametric_correlation_significance,
    nonparametric_correlation_significance, fisher_confidence_intervals,
    pearson, spearmans_rho, G_fit, ANOVA_one_way, kruskal_wallis, mw_test, 
    mw_boot, t_paired, mc_t_two_sample, t_two_sample,
    fisher, kendalls_tau, assign_correlation_pval)
from qiime.util import biom_taxonomy_formatter

"""
Library for test_group_significance.py and test_gradient_correlation.py. 
The code in this library is based around two central frameworks. For the group
significance tests the framework is as follows:
The OTU table is a rowXcolumn (otuXsample) matrix. The mapping file specifies 
certain groups of samples based on metadata (eg. samples 1,2,6,9 are obese mice 
and samples 3,4 5,12 are lean mice). The code slices the OTU matrix into rows 
(individual otus) and groups together columns (samples) which have the same 
metadata value based on the passed metadata field. These groupings are then 
compared using the specified test. 
For the gradient correlation tests the framework is as follows:
Each row of the OTU table is correlated with a numeric value found in the some 
metadata category of the mapping file. No grouping within categories occurs. 
Some abbreviations that are used in this code are:
pmf - parsed mapping file. Nested dict created by parse_mapping_file_to_dict 
 which has as top level keys the sample IDs and then all assocaited metadata 
 in a dictionary with the mapping file column headers as keys. 
bt - biom table object. Created with parse_biom_table. 
row - row is used in several places (eg. row_generator). The 'row' being 
 returned is actually a list of arrays that comes from a single row, and a 
 collection of grouped columns from the OTU table (for the group significance 
 tests). For the gradient correlations a row is actually a full row of the OTU.
"""

# Pursuant to cogent/qiime coding guidelines, globals are uppercase. These dicts
# map the script interface names to the actual functions running these tests.
CORRELATION_TEST_CHOICES = {'pearson': pearson, 'spearman': spearmans_rho,
    'kendall': kendalls_tau}

GROUP_TEST_CHOICES = {'ANOVA': ANOVA_one_way, 'g_test': G_fit, 
    'kruskal_wallis': kruskal_wallis, 'parametric_t_test': t_two_sample,
    'nonparametric_t_test': mc_t_two_sample, 'mann_whitney_u': mw_test, 
    'bootstrap_mann_whitney_u': mw_boot}

TWO_GROUP_TESTS = ['parametric_t_test', 'nonparametric_t_test', 
    'mann_whitney_u', 'bootstrap_mann_whitney_u']

CORRELATION_PVALUE_CHOICES = ['parametric_t_distribution', 'fisher_z_transform',
    'bootstrapped']

# Functions for group significance testing

def get_sample_cats(pmf, category):
    """Create {SampleID:category_value} for samples in parsed mf dict.

    Inputs:
     pmf - parsed mapping file. Described at top of library.
     category - string, key in the pmf.
    """
    # ignore samples where the value in the mapping file is empty
    return {k:pmf[k][category] for k in pmf.keys() if pmf[k][category] != ""}

def get_cat_sample_groups(sam_cats):
    """Create {category_value:[samples_with_that_value} dict.

    Inputs:
     sam_cats - dict, output of get_sample_cats."""
    cat_sam_groups = {group:[] for group in set(sam_cats.values())}
    [cat_sam_groups[v].append(k) for k,v in sam_cats.items()]
    return cat_sam_groups

def get_sample_indices(cat_sam_groups, bt):
    """Create {category_value:index_of_sample_with_that_value} dict.

    Inputs: 
     cat_sam_groups - dict, output of get_cat_sample_groups.
     bt - biom table object. Described at top of library.
    """
    return {k:[bt.SampleIds.index(i) for i in v] for k,v in cat_sam_groups.items()}

def group_significance_row_generator(bt, cat_sam_indices):
    """Produce generator that feeds lists of arrays to group significance tests.

    Read library documentation for description of what a 'row' is. 
    Inputs: 
     bt - biom table object. Described at top of library.
     cat_sam_indices - dict, output of get_sample_indices.
    """
    data = array([bt.observationData(i) for i in bt.ObservationIds])
    return ([row[cat_sam_indices[k]] for k in cat_sam_indices] for row in data)

def run_group_significance_test(data_generator, test, test_choices, reps=1000):
    """Run any of the group significance tests.

    Inputs:
     data_generator - generator object, output of row_generator. The output of 
      each iter of the data_generator is a list of arrays which is fed to one 
      of the tests.
     test - string, key of group_test_choices. the script interface name for the
      functions.
     test_choices - dictionary, defined as global at top of library.
     reps - int, number of reps or permutations to do for the bootstrapped 
      tests.
    Ouputs are lists of test statistics, p values, and means of each group.
    """
    pvals, test_stats, means = [], [], []
    for row in data_generator:
        if test == 'nonparametric_t_test':
            test_stat, _, _, pval = test_choices[test](row[0], row[1], 
                permutations=reps)
        elif test == 'bootstrap_mann_whitney_u':
            test_stat, pval = test_choices[test](row[0], row[1], num_reps=reps)
        elif test in ['parametric_t_test', 'mann_whitney_u']:
            test_stat, pval = test_choices[test](row[0], row[1])
        else:
            # ANOVA, kruskal_wallis, G_fit will get caught here
            test_stat, pval = test_choices[test](row)
        test_stats.append(test_stat)
        pvals.append(pval)
        means.append([i.mean() for i in row])
    return test_stats, pvals, means

def group_significance_output_formatter(bt, test_stats, pvals, fdr_pvals, 
    bon_pvals, means, cat_sample_indices):
    """Format the output for gradient tests so it can be easily written.

    Inputs are lists of test statistics, pvalues, fdr corrected pvalues, 
    bonferonni corrected pvalues, group means, and the dict of
    {category:sample_index}.
    """
    header = ['OTU', 'Test-Statistic', 'P', 'FDR_P', 'Bonferroni_P']
    header += ['%s_mean' % i for i in cat_sample_indices.keys()]
    # find out if bt came with taxonomy. this could be improved
    if bt.ObservationMetadata is None:
        include_taxonomy = False
    else:
        include_taxonomy = True
        header += ['Taxonomy']
    num_lines = len(pvals)
    lines = ['\t'.join(header)]
    for i in range(num_lines):
        tmp = [bt.ObservationIds[i], test_stats[i], pvals[i], fdr_pvals[i], 
            bon_pvals[i]] + means[i] 
        if include_taxonomy:
            tmp.append(biom_taxonomy_formatter(bt.ObservationMetadata[i]))
        lines.append('\t'.join(map(str, tmp)))
    return lines

# Functions for gradient correlation testing

def longitudinal_row_generator(bt, pmf, category, hsid_to_samples, 
    hsid_to_sample_indices):
    """Produce generator that feeds lists of arrays to longitudinal tests.

    This function groups samples based on hsid_to_samples which is a dict of 
    {value:[list of sample ids]}. It returns nested lists where each row is a 
    tuple with the values of the observations in that row grouped by the sample 
    groupings found in hsid_to_samples, and then the metadata value of those
    samples in the mapping file based on the given category. Example output row:
    ([array([ 28.,  52.]), array([ 16.,  77.]), array([ 78.,  51.])],
     [array([ 1.,  2.]),   array([ 5.,  6.]),   array([ 4.,  3.])]),
    Inputs: 
     bt - biom table object. Described at top of library.
     pmf - nested dict, parsed mapping file object.
     category - str, column header of parsed_mapping_file. 
     hsid_to_samples - nested_dict, dict where top level key is a value which 
      all sample ids in the list of values share. ex {'subject1':['s1', 's2']}.
     hsid_to_sample_indices - nested dict, conversion of hsid_to_samples where 
      instead of sample ids, column indices in the biom file are provided.
    """
    data = array([bt.observationData(i) for i in bt.ObservationIds])
    try: #create longitudinal data values from the mapping file
        l_arr = [array([pmf[sid][category] for sid in sids]).astype(float) for \
            hsid,sids in hsid_to_samples.items()]
    except ValueError:
        raise ValueError("Couldn't convert values to float. Can't continue.")
    return ((array([row[v] for k,v in hsid_to_sample_indices.items()]),l_arr) \
        for row in data)

def run_longitudinal_correlation_test(data_generator, test, test_choices):
    """Run longitudinal correlation test."""
    rs, combo_pvals, combo_rhos, homogenous = [], [], [], []
    test_fn = test_choices[test]
    for obs_vals, gradient_vals in data_generator:
        rs_i, pvals_i = [], []
        for i in range(len(obs_vals)):
            # calculate test stat
            r = test_fn(obs_vals[i], gradient_vals[i])
            rs_i.append(r)
            # calculate pval
            if test=='kendall':
                pval = kendall_pval(r, len(obs_vals[i]))
            else:
                pval = 
            pval = parametric_correlation_significance(r, len(obs_vals[i]))
            pvals_i.append(pval)
        # append to values for all individuals
        rs.append(rs_i)
        # compute fisher stats
        combo_pvals.append(fisher(pvals_i))
        sample_sizes = [len(vals) for vals in obs_vals]
        fisher_rho, h = fisher_population_correlation(rs[-1], sample_sizes)
        combo_rhos.append(fisher_rho)
        homogenous.append(h)

    return rs, combo_pvals, combo_rhos, homogenous

def longitudinal_correlation_formatter(bt, combo_rhos, combo_pvals, homogenous, 
    fdr_ps, bon_ps, corrcoefs, hsid_to_samples):
    """Format output from longitudinal tests to be written.

    Inputs are biom table, list of test statistics, dict of {hsid:sample id}.
    """
    ind_order = ', '.join(hsid_to_samples.keys())
    header = ['OTU', 'Fisher Combined Rho', 'P Rho is Homogenous', 
        'Fisher Combined P', 'FDR P', 'Bonferroni P', 'Corrcoefs', 
        'Individual Order']
    # find out if bt came with taxonomy. this could be improved
    if bt.ObservationMetadata is None:
        include_taxonomy = False
    else:
        include_taxonomy = True
        header += ['Taxonomy']
    num_lines = len(combo_rhos)
    lines = ['\t'.join(header)]
    for i in range(num_lines):
        tmp = [bt.ObservationIds[i], combo_rhos[i], homogenous[i], 
            combo_pvals[i], fdr_ps[i],  bon_ps[i], ', '.join(map(str,
            corrcoefs[i])), ind_order]
        if include_taxonomy:
            tmp.append(biom_taxonomy_formatter(bt.ObservationMetadata[i]))
        lines.append('\t'.join(map(str, tmp)))
    return lines

def correlation_row_generator(bt, pmf, category):
    """Produce a generator that feeds lists of arrays to any gradient test.

    In this function, a row is a full row of the OTU table, a single 1D array.
    Inputs: 
     bt - biom table object. Described at top of library.
     cat_sam_indices - dict, output of get_sample_indices.
    """
    data = array([bt.observationData(i) for i in bt.ObservationIds])
    # ensure that the order of the category vector sample values is the same 
    # as the order of the samples in data. otherwise will have hard to 
    # diagnose correspondence issues
    try:
        cat_vect = array([pmf[s][category] for s in bt.SampleIds]).astype(float)
        return ((row,cat_vect) for row in data)
    except ValueError:
        raise ValueError("Mapping file category contained data that couldn't "+\
            "be converted to float. Can't continue.")

def run_correlation_test(data_generator, test, test_choices, np_test=False):
    """Run correlation tests."""
    corr_coefs, p_pvals, np_pvals, ci_highs, ci_lows = [], [], [], [], []
    test_fn = test_choices[test]
    for row in data_generator:
        # kendalls tau calculates its own paramteric p value
        if test == 'kendall':
            test_stat, p = test_fn(row[0], row[1])
            p_pval = p
        else: # spearman, pearson executed here
            test_stat = test_fn(row[0], row[1])
            p_pval = parametric_correlation_significance(test_stat, len(row[0]))
        np_pval = nonparametric_correlation_significance(test_stat, test_fn, 
            row[0], row[1])
        ci_low, ci_high = fisher_confidence_intervals(test_stat,len(row[0]))
        corr_coefs.append(test_stat)
        p_pvals.append(p_pval)
        np_pvals.append(np_pval)
        ci_lows.append(ci_low)
        ci_highs.append(ci_high)
    return corr_coefs, p_pvals, np_pvals, ci_highs, ci_lows

def correlation_output_formatter(bt, corr_coefs, p_pvals, p_pvals_fdr, 
    p_vals_bon, np_pvals, np_pvals_fdr, np_pvals_bon, ci_highs, 
    ci_lows):
    """Format the output of the correlations for easy writing."""
    header = ['OTU', 'Correlation_Coef', 'parametric_P', 'parametric_P_FDR',
        'parametric_P_Bon', 'nonparametric_P', 'nonparametric_P_FDR',
        'nonparametric_P_Bon', 'confidence_low', 'confidence_high']
    # find out if bt came with taxonomy. this could be improved
    if bt.ObservationMetadata is None:
        include_taxonomy = False
    else:
        include_taxonomy = True
        header += ['Taxonomy']
    num_lines = len(corr_coefs)
    lines = ['\t'.join(header)]
    for i in range(num_lines):
        tmp = [bt.ObservationIds[i], corr_coefs[i], p_pvals[i], p_pvals_fdr[i], 
            p_vals_bon[i], np_pvals[i], np_pvals_fdr[i], np_pvals_bon[i], 
            ci_highs[i], ci_lows[i]]
        if include_taxonomy:
            tmp.append(biom_taxonomy_formatter(bt.ObservationMetadata[i]))
        lines.append('\t'.join(map(str, tmp)))
    return lines

def paired_t_generator(bt, s_before, s_after):
    """Produce a generator to run paired t tests on each OTU."""
    b_data = vstack([bt.sampleData(i) for i in s_before]).T
    a_data = vstack([bt.sampleData(i) for i in s_after]).T
    return ((b_data[i], a_data[i]) for i in range(len(bt.ObservationIds)))

def run_paired_t(data_generator):
    """Run paired t test on data."""
    test_stats, pvals = [], []
    for b_data, a_data in data_generator:
        test_stat, pval = t_paired(b_data, a_data)
        test_stats.append(test_stat)
        pvals.append(pval)
    return test_stats, pvals

def paired_t_output_formatter(bt, test_stats, pvals, fdr_pvals, bon_pvals):
    """Format the output for all tests so it can be easily written."""
    header = ['OTU', 'Test-Statistic', 'P', 'FDR_P', 'Bonferroni_P']
    # find out if bt came with taxonomy. this could be improved
    if bt.ObservationMetadata is None:
        include_taxonomy = False
    else:
        include_taxonomy = True
        header += ['Taxonomy']
    num_lines = len(pvals)
    lines = ['\t'.join(header)]
    for i in range(num_lines):
        tmp = [bt.ObservationIds[i], test_stats[i], pvals[i], fdr_pvals[i], 
            bon_pvals[i]]
        if include_taxonomy:
            tmp.append(biom_taxonomy_formatter(bt.ObservationMetadata[i]))
        lines.append('\t'.join(map(str, tmp)))
    return lines

# Functions used by both scripts

def sort_by_pval(lines, ind):
    """Sort lines with pvals in descending order.

    ind is the index of each line, split on \t, that is to be used for sorting.
    """
    return [lines[0]]+sorted(lines[1:], key=lambda x: float(x.split('\t')[ind])
        if not isnan(float(x.split('\t')[ind])) else inf)
