import petab
import amici
import pandas as pd
from typing import Union, Optional, Iterable, List
from ..problem import Problem
from ..result import Result
from ..petab import PetabImporter
from petab.C import OBSERVABLE_ID, CONDITION_ID
from amici.petab_import import _create_model_output_dir_name


# should we specify Optimizer here?
class DesignProblem(dict):
    """
    The problem formulation for an experimental design setting

    Parameters
    ----------
    experiment_list:
        list of dicts, each dict with entries 'id' and 'measurement_df'.
        Entries 'condition_df', 'observable_df' are optional.
        Each row in 'measurement_df' specifies one conditions to add to the
        existing dataframes
    model:
        the amici model,
        if new observable are defined in 'experiment_list' a new amici_model
        is created which contains all new observables
    problem:
        the pypesto problem for the initial setting
    result:
        the pypesto result for the initial setting
    petab_problem:
        the petab problem for the initial setting
    initial_x:
        can be either a list of the parameters to be used for the forward
        simulation, or a list of multiple parameter sets. If multiple are
        passed the code will return averaged values over all parameter sets in
        the end.
    criteria_list:
        list of criteria names, specifies which criteria values should be
        computed
    const_for_hess:
        a constant that can be added to the eigenvalues before computing the
        criteria values
    n_save_combi_result:
        if the full combinatorial space is checked for the best
        combination of candidates from 'experiment_list' only the best
        'n_save_combi_result' many will be saved (for each criteria)
    number_of_measurements:
        how many new measurements are to be added for one candidate from
        experiment_list
    """

    def __init__(self,
                 experiment_list: list,
                 model: Union['amici.Model', 'amici.ModelPtr'],
                 problem: Problem,
                 petab_problem: petab.Problem,
                 result: Optional[Result] = None,
                 initial_x: Optional[Iterable] = None,
                 criteria_list: List[str] = None,
                 chosen_criteria: str = 'det',
                 const_for_hess: float = None,
                 n_save_combi_result: int = None,
                 number_of_measurements: int = 1):

        super().__init__()

        if criteria_list is None:
            criteria_list = ['det', 'trace', 'ratio', 'rank', 'eigmin',
                             'number_good_eigvals',
                             'det_modified', 'trace_modified',
                             'ratio_modified', 'rank_modified',
                             'eigmin_modified',
                             'number_good_eigvals_modified',
                             ]

        if initial_x is None:
            if result is None:
                ValueError("You have to pass either the parameters x or the "
                           "pypesto result")
            initial_x = result.optimize_result.get_for_key('x')[0]

        if n_save_combi_result is None:
            n_save_combi_result = 20

        self.experiment_list = experiment_list
        self.problem = problem
        self.result = result
        self.petab_problem = petab_problem
        self.model = self.get_super_model(model)
        self.initial_x = initial_x
        self.criteria_list = criteria_list
        self.chosen_criteria = chosen_criteria
        self.const_for_hess = const_for_hess
        self.number_of_measurements = number_of_measurements
        self.n_save_combi_result = n_save_combi_result

        self.modified_criteria = [crit for ind, crit in
                                  enumerate(self.criteria_list) if
                                  '_modified' in crit]
        self.non_modified_criteria = [crit for ind, crit in
                                      enumerate(self.criteria_list) if
                                      crit not in self.modified_criteria]
        # self.modified_criteria will contain only the criteria names,
        # not the "_modified" at the end
        self.modified_criteria = [crit_modified.replace("_modified", "")
                                  for crit_modified in self.modified_criteria]

        self.check_criteria()

        # update condition_df to include all new conditions
        # (observable was already done when getting the model)
        self.write_super_condition_df()

        # sanity checks for lengths of df in experiment_list
        # if not self.experiment_list:
        #     raise ValueError('you need to pass a nonempty list of
        #     candidates')
        # for dict in self.experiment_list:
        #     if 'condition_df' in dict and dict['condition_df'] is not None \
        #             and len(dict['condition_df'].columns) \
        #             != len(self.petab_problem.condition_df.columns):
        #         raise ValueError(
        #             'condition dataframe in given candidates has wrong
        #             length')
        #     if 'observable_df' in dict and dict['observable_df'] is not
        #     None \
        #             and len(dict['observable_df'].columns) != \
        #             len(self.petab_problem.observable_df.columns):
        #         raise ValueError(
        #             'observable dataframe in given candidates has wrong '
        #             'length')
        #     if len(dict['measurement_df'].columns) != len(
        #             self.petab_problem.measurement_df.columns):
        #         raise ValueError(
        #             'measurement dataframe in given candidates has wrong '
        #             'length')

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def get_super_model(self, model: Union['amici.Model', 'amici.ModelPtr']):
        """
        create the amici model which contains all newly defined observables
        which we can use throughout the experimental design process
        if no new observables are defined in 'experiment_list', return the
        original model
        If new observables are defined they must have different Ids (for
        each candidate) to distinguish them or be completely identical!
        """
        list_of_new_dfs = [dict['observable_df'] for dict in
                           self.experiment_list if 'observable_df' in dict
                           and dict['observable_df'] is not None]

        if not list_of_new_dfs:
            return model
        else:
            # merge them
            new_conditions = pd.concat(list_of_new_dfs)

            # remove duplicates
            new_conditions = new_conditions.reset_index().drop_duplicates(
            ).set_index(OBSERVABLE_ID)

            observable_df = self.petab_problem.observable_df.reset_index()
            observable_df = observable_df.append(new_conditions.reset_index())
            observable_df = observable_df.set_index(OBSERVABLE_ID)
            self.petab_problem.observable_df = observable_df

            output_dir = _create_model_output_dir_name(
                self.petab_problem.sbml_model) + '_super'
            importer = PetabImporter(self.petab_problem,
                                     output_folder=output_dir,
                                     model_name=self.petab_problem.
                                     sbml_model.getId() + '_super')
            problem = importer.create_problem()
            super_model = problem.objective.amici_model

            # super_model = import_petab_problem(self.petab_problem,
            #                                    model_output_dir=output_dir,
            #                                    model_name=self.petab_problem.
            #                                    sbml_model.getId() + '_super')
            return super_model

    def write_super_condition_df(self):
        """
        if new conditions are defined in 'experiment_list' add all of them to
        the petab_problem
        """
        list_of_new_dfs = [dict['condition_df'] for dict in
                           self.experiment_list if 'condition_df' in dict
                           and dict['condition_df'] is not None]

        if not list_of_new_dfs:
            return
        else:
            # merge them
            new_conditions = pd.concat(list_of_new_dfs)

            # remove duplicates
            new_conditions = new_conditions.reset_index().drop_duplicates(
            ).set_index(CONDITION_ID)

            condition_df = self.petab_problem.condition_df.reset_index()
            condition_df = condition_df.append(new_conditions.reset_index())
            condition_df = condition_df.set_index(CONDITION_ID)
            self.petab_problem.condition_df = condition_df
            return

    def check_criteria(self):
        """
        check if the requested criteria are supported
        """
        okay_criteria = ['det', 'det_modified', 'eigmin', 'eigmin_modified',
                         'trace', 'trace_modified', 'ratio',
                         'ratio_modified',
                         'rank', 'rank_modified', 'number_good_eigvals',
                         'number_good_eigvals_modified', 'trace_log',
                         'trace_log_modified']
        if not set(self.criteria_list).issubset(set(okay_criteria)):
            raise KeyError("one of the specified criteria is not supported")

        # should we have a standard value here? or throw an error?
        if self.modified_criteria and self.const_for_hess is None:
            self.const_for_hess = 10 ** (-4)
        return

    """
    def write_super_observable_df(self):
    list_of_new_dfs = [dict['observable_df'] for dict in
                           self.experiment_list if 'observable_df' in dict
                           and dict['observable_df'] is not None]

    if not list_of_new_dfs:
        return
    else:
        # merge them
        new_conditions = pd.concat(list_of_new_dfs)

        # remove duplicates
        new_conditions = new_conditions.reset_index().drop_duplicates(
        ).set_index(OBSERVABLE_ID)

        observable_df = self.petab_problem.observable_df.reset_index()
        observable_df = observable_df.append(new_conditions.reset_index())
        observable_df = observable_df.set_index(OBSERVABLE_ID)
        self.petab_problem.observable_df = observable_df
        return
    """