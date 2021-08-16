import pypesto
import pypesto.logging
import pypesto.petab
import petab
import amici
import logging

import numpy as np
import pandas as pd


from pypesto.hierarchical.optimal_scaling_solver import OptimalScalingInnerSolver
from pypesto.hierarchical.problem import InnerProblem

def run_optimization(importer, optimizer, history_name, num_starts, min_gap):
    """Run optimization"""
    pypesto.logging.log_to_console(logging.INFO)

    objective = importer.create_objective(force_compile=True)
    problem = importer.create_problem(objective, force_compile=True)

    option = pypesto.optimize.OptimizeOptions(allow_failed_starts=True)

    engine = pypesto.engine.SingleCoreEngine()

    problem.objective.calculator.inner_solver = OptimalScalingInnerSolver(options={'method': 'standard',
                                                                                   'reparameterized': False,
                                                                                   'intervalConstraints': 'max',
                                                                                   'minGap': min_gap})

    history_options = pypesto.HistoryOptions(trace_record=True, storage_file=history_name)
    np.random.seed(num_starts)
    result = pypesto.optimize.minimize(problem,
                                       n_starts=1,
                                       optimizer=optimizer,
                                       engine=engine,
                                       options=option,
                                       history_options=history_options)
    return result

def get_optimizer(optimizer_name):
    """Return pyPESTO optimizer"""
    opt_all = {'L-BFGS-B': pypesto.optimize.ScipyOptimizer(method='L-BFGS-B',
                                                           options={'disp': True, 'fatol': 1e-8, 'gtol': 1e-10}),
               'SLSQP': pypesto.optimize.ScipyOptimizer(method='SLSQP', options={'disp': True, 'fatol': 1e-8, 'gtol': 1e-10}),
               'ipopt': pypesto.optimize.IpoptOptimizer(
                   options={'disp': 5, 'maxiter': 200, 'accept_after_max_steps': 20}),
               'pyswarm': pypesto.optimize.PyswarmOptimizer(options={}),
               'powell': pypesto.optimize.ScipyOptimizer(method='Powell',
                                                         options={'disp': True, 'fatol': 1e-8})}
    return opt_all[optimizer_name]

def main():
    """Napisi opis..."""

   # petab_problem = petab.Problem.from_yaml(
   # '/home/zebo/Documents/GitHub/examples/Boehm_JProteomeRes2014OptimalScaling_HardConstraints/Boehm_JProteomeRes2014OptimalScaling_HardConstraints.yaml')

    petab_problem = petab.Problem.from_yaml(
    '/home/zebo/Documents/Benchmark-Models-PEtab-master/Benchmark-Models/Boehm_JProteomeRes2014/Boehm_JProteomeRes2014.yaml')

    petab.flatten_timepoint_specific_output_overrides(petab_problem)

    importer = pypesto.petab.PetabImporter(petab_problem)
    model=importer.create_model()

    optimizer = get_optimizer('SLSQP')
    print("tu sam")
    run_optimization(importer, optimizer, history_name= 'povijest', num_starts=1, min_gap=1e-16)

if __name__ == "__main__":
    main()