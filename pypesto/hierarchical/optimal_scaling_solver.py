from math import e
import warnings
import math
import csv
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from ..optimize import Optimizer
from .optimal_scaling_problem import OptimalScalingProblem
from .parameter import InnerParameter
from .problem import InnerProblem
from .solver import InnerSolver

REDUCED = 'reduced'
STANDARD = 'standard'
MAXMIN = 'max-min'
MAX = 'max'


class OptimalScalingInnerSolver(InnerSolver):
    """
    Solve the inner subproblem of the
    optimal scaling approach for ordinal data.
    """

    def __init__(self,
                 optimizer: Optimizer = None,
                 options: Dict = None):

        self.optimizer = optimizer
        self.options = options
        if self.options is None:
            self.options = OptimalScalingInnerSolver.get_default_options()
        if self.options['method'] == STANDARD \
                and self.options['reparameterized']:
            raise NotImplementedError(
                'Combining standard approach with '
                'reparameterization not implemented.'
            )
        self.x_guesses = None

    def solve(
            self,
            problem: InnerProblem,
            sim: List[np.ndarray],
            sigma: List[np.ndarray],
            scaled: bool,
    ) -> list:
        """
        Get results for every group (inner optimization problem)

        Parameters
        ----------
        problem:
            InnerProblem from pyPESTO hierarchical
        sim:
            Simulations from AMICI
        sigma:
            List of sigmas (not needed for this approach)
        scaled:
            ...
        """
        optimal_surrogates = []
        #print("EVO SIM:", sim)
        #breakpoint()
        simulation_indices = problem.simulation_indices
        for gr in problem.get_groups_for_xs(InnerParameter.OPTIMALSCALING):
            quantitative_data = problem.get_quantitative_data_for_group(gr)
            quantitative_data = quantitative_data.sort_values(by=['simulationConditionId', 'time'])
            #print("Running for group: ", gr)
            surrogate_opt_results = spline_optimize_surrogate(gr, sim, quantitative_data, simulation_indices, self.options)
            optimal_surrogates.append(surrogate_opt_results)
        return optimal_surrogates

    @staticmethod
    def calculate_obj_function(x_inner_opt: list):
        """
        Calculate the inner objective function from a list of inner
        optimization results returned from compute_optimal_surrogate_data

        Parameters
        ----------
        x_inner_opt:
            List of optimization results
        """

        if False in [x_inner_opt[idx]['success'] for idx in range(len(x_inner_opt))]:
            obj = np.nan
            warnings.warn(f"Inner optimization failed.")
        else:
            obj = np.sum(
                [x_inner_opt[idx]['fun'] for idx in range(len(x_inner_opt))]
            )
        # print(obj)
        #print("I calculated the obj function with optimized inner pars")
        return obj

    def calculate_gradients(self,
                            problem: OptimalScalingProblem,
                            x_inner_opt,
                            sim,
                            sy,
                            parameter_mapping,
                            par_opt_ids,
                            amici_model,
                            snllh,
                            ):
        #breakpoint()
        simulation_indices = problem.simulation_indices
        condition_map_sim_var = parameter_mapping[0].map_sim_var
        #print(condition_map_sim_var)
        par_sim_ids = list(amici_model.getParameterIds())
        par_sim_idx=-1 # DOES THIS WOrK IF THE Pars are not connected order 
        #print(par_sim_ids)
        # TODO: Doesn't work with condition specific parameters
        for par_sim, par_opt in condition_map_sim_var.items():
            if not isinstance(par_opt, str):
                continue
            if par_opt.startswith('optimalScaling_'):
                continue
            #par_sim_idx = par_sim_ids.index(par_sim) ZEBO REPLACE
            par_sim_idx += 1
            inner_par_idx = 0
            par_opt_idx = par_opt_ids.index(par_opt)
    
            grad = 0.0
            #print(par_sim, par_opt)
            for idx, gr in enumerate(problem.get_groups_for_xs(InnerParameter.OPTIMALSCALING)):
                xi = np.asarray(x_inner_opt[inner_par_idx]['x'])
                sim_all = get_sim_all_for_quantitative(gr, sim, simulation_indices)
                #print(xi)
                inner_par_idx += 1

                
                
                sy_all = get_sy_all_for_quantitative(gr, sy, par_sim_idx, simulation_indices)
                quantitative_data = problem.get_quantitative_data_for_group(gr)
                quantitative_data = quantitative_data.sort_values(by=['simulationConditionId', 'time'])
                # with pd.option_context('display.max_rows', None, 'display.max_columns', None):  # more options can be specified also
                #     print(quantitative_data)
                measurements = quantitative_data.measurement.values
                #print("xi for group ", gr, ": \n", xi)
                #print(measurements)
                #print(sim_all)
                #breakpoint()
                # print(sy_all)

                #N = self.options['numberofInnerParams'][int(gr)-1]
                #delta_c = self.options['deltac'][int(gr)-1]
                N, delta_c, c_1 = get_spline_domain(sim_all)
                
                with open('/home/zebo/Desktop/numerical_spline_xi.csv', 'a', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(np.block([np.asarray([N, delta_c, c_1]), xi, np.asarray([-1]), sim_all]))

                C = np.diag(-np.ones(N), -1) \
                    + np.diag(np.ones(N +1))
                C = C[:-1, :-1]

                w = np.sum(np.abs(sim_all)) + 1e-8
                w_dot = -1 * np.sum(sy_all) / (w**2)
                
                Jacobian, rhs = spline_get_Jacobian(gr, sim_all, measurements, self.options)
                mu = spline_get_mu(Jacobian, rhs, xi, w, C)
                
                xi_dot = spline_get_dxi_dtheta(gr, sim_all, sy_all, measurements, xi, w, w_dot, C, mu, self.options)
                
                # breakpoint()
                # print(C)
                # print(Jacobian, rhs)
                # print(mu)
                # print(xi_dot)
                #Let's calculate the gradient now:
                df_dxi = np.zeros(N)
                df_dyk = 0
                res = 0
                for y_k, z_k, y_dot_k in \
                        zip(sim_all, measurements, sy_all):
                    n=math.ceil((y_k - c_1)/ delta_c) + 1
                    if(n>N): n=N+1
                    i=n-1
                    #calculate df_dxi
                    if(n<N+1):
                        df_dxi[i] += -2 * (z_k - (y_k - c_1 - (n-2)*delta_c)*(xi[i] - xi[i-1])/delta_c - xi[i-1]) * (y_k - c_1 - (n-2)*delta_c) / delta_c
                    if(n>1 and n<N+1):
                        df_dxi[i-1] += -2 * (z_k - (y_k - c_1 - (n-2)*delta_c)*(xi[i] - xi[i-1])/delta_c - xi[i-1]) * (c_1 + (n-1)*delta_c - y_k) / delta_c
                    if(n==N+1):
                        df_dxi[i-1] += -2 * (z_k - xi[i-1])
                    #calculate df_dyk (without w_dot term)
                    if(n < N+1 and n >1):
                        df_dyk+= -2 * (z_k - (y_k - c_1 - delta_c * (n-2))*(xi[i] - xi[i-1])/delta_c -xi[i-1]) * (xi[i] - xi[i-1]) * y_dot_k /delta_c
                    elif(n==1):
                        df_dyk+= -2 * (z_k - y_k*xi[i]/c_1) * xi[i] * y_dot_k /c_1
                    #calculate res for the w_dot term
                    if(n < N+1 and n >1):
                        res+= (z_k - (y_k - c_1 - delta_c * (n-2))*(xi[i] - xi[i-1])/delta_c -xi[i-1])**2
                    elif(n==N+1):
                        res+= (z_k - xi[i-1])**2
                    elif(n==1):
                        res+= (z_k - y_k*xi[i]/c_1)**2
                
                df_dyk = np.divide(df_dyk, w)
                df_dyk += w_dot * res
                df_dxi = np.divide(df_dxi, w)
                grad += df_dxi.dot(xi_dot) + df_dyk

            snllh[par_opt_idx] = grad
        #print("I calculated the grad with optimized inner pars")
        return snllh

    @staticmethod
    def get_default_options() -> Dict:
        """
        Return default options for solving the inner problem,
        if no options provided
         """
        options = {'method': 'reduced',
                   'reparameterized': True,
                   'intervalConstraints': 'max',
                   'minGap': 1e-16}
        return options

def spline_optimize_surrogate(gr: float,
                              sim: List[np.ndarray],
                              quantitative_data: pd.DataFrame,
                              simulation_indices: List,
                              options: Dict):
    """Run optimization for inner problem"""

    from scipy.optimize import minimize
   
    sim_all = get_sim_all_for_quantitative(gr, sim, simulation_indices)

    measurements = quantitative_data.measurement.values
    w = np.sum(np.abs(sim_all)) + 1e-8

    def obj_surr(x):
        return obj_spline(gr, x, sim_all, w, measurements, options)

    inner_options = \
        get_spline_inner_options(gr, measurements, options, sim_all)
    try:
        results = minimize(obj_surr, **inner_options)
    #this not needed probably?
    except:
        print('x0 violate bound constraints. Retrying with array of zeros.')
        inner_options['x0'] = np.zeros(len(inner_options['x0']))
        results = minimize(obj_surr, **inner_options)
    #breakpoint()
    # print("sim_all: \n ", sim_all, "\n", 
    #       "measurements : \n", measurements, "\n",
    #       "xi: \n ", results['x'])
    return results

def obj_spline(gr: float,
               optimal_xi: np.ndarray,
               sim_all: np.ndarray,
               w: float,
               measurements: np.ndarray,
               options: Dict):
        obj = 0
        w = np.sum(np.abs(sim_all)) + 1e-8
        #N = options['numberofInnerParams'][int(gr)-1]
        #delta_c = options['deltac'][int(gr)-1]
        N, delta_c, c_1 = get_spline_domain(sim_all)

        for y_k, z_k in \
                zip(sim_all, measurements):
            n=math.ceil((y_k - c_1)/ delta_c) + 1
            if(n==1 and c_1 != delta_c): 
                print("n=1 pazii error")
                breakpoint()
            if(n>N): n=N+1
            i = n-1
            if(n < N+1 and n >1):
                obj+= (z_k - (y_k - c_1 - delta_c * (n-2))*(optimal_xi[i] - optimal_xi[i-1])/delta_c -optimal_xi[i-1])**2
            elif(n==N+1):
                obj+= (z_k - optimal_xi[i-1])**2
            elif(n==1):
                obj+= (z_k - y_k*optimal_xi[i]/c_1)**2
        obj = np.divide(obj, w)
        #print("Obj for group ", gr, ": ", obj)
        return obj

def get_spline_inner_options(gr: float,
                             measurements: np.ndarray,
                             options: Dict,
                             sim_all: np.ndarray) -> Dict:

    """Return default options for scipy optimizer"""

    from scipy.optimize import Bounds
    N , delta_c, c_1 = get_spline_domain(sim_all)
    
    min_all=max_all=measurements[0]
    for m in measurements:
        if(m>max_all): max_all = m
        if(m<min_all): min_all = m    
    range_all = max_all - min_all

    x0 = np.linspace(np.max([min_all - 0.3*range_all, 0]), 
                     max_all + 0.3*range_all, 
                     N+1)[1:]
                     
    constraints = get_monotonicity_constraints(N)
    inner_options = {'x0': x0, 'method': 'SLSQP',
                     'options': {'maxiter': 2000, 'ftol': 1e-10, 'disp': True},
                     'constraints': constraints}

    return inner_options

def get_monotonicity_constraints(N: int) -> Dict:
    """Return constraints for inner optimization"""

    a = np.diag(-np.ones(N), -1) \
        + np.diag(np.ones(N +1))
    a = a[:-1, :-1]
    b = np.zeros(N)
    ineq_cons = {'type': 'ineq', 'fun': lambda x: a.dot(x) - b}

    return ineq_cons

def spline_get_Jacobian(gr,
                        sim_all,
                        measurements,
                        options):
        #breakpoint()  
        # if(gr==1.0):
        #     print("Group ", gr, ": \n", measurements)   
        #     print(sim_all)
        
        #N = options['numberofInnerParams'][int(gr)-1]
        #delta_c = options['deltac'][int(gr)-1]
        N, delta_c, c_1 = get_spline_domain(sim_all)
        Jacobian = np.zeros((N,N))
        rhs = np.zeros(N)

        for y_k, z_k in \
                zip(sim_all, measurements):
            n=math.ceil((y_k - c_1)/ delta_c) + 1
            if(n>N): n=N+1
            i = n-1 #just the iterator to go over the Jacobian matrix
            #ALSO MAKE THE LAST MONOTONICITY STEP
            if(n<N+1):
                if(n>1): Jacobian[i][i-1] += (y_k - c_1 - (n-2)*delta_c) * (c_1 + (n-1)*delta_c - y_k)
                Jacobian[i][i] += (y_k - c_1 - (n-2)*delta_c)**2
                rhs[i] += z_k * (y_k - c_1 - (n-2)*delta_c)*delta_c
            if(n>1 and n<N+1):
                Jacobian[i-1][i-1] += (c_1 + (n-1)*delta_c - y_k)**2
                if(n<N+1): Jacobian[i-1][i] += (y_k - c_1 - (n-2)*delta_c) * (c_1 + (n-1)*delta_c - y_k)
                rhs[i-1] += z_k * (c_1 + (n-1)*delta_c - y_k)*delta_c
            if(n==N+1):
                Jacobian[i-1][i-1] += delta_c**2
                rhs[i-1] += z_k * delta_c**2
        #print(Jacobian)
        Jacobian = np.divide(Jacobian, delta_c**2)
        rhs = np.divide(rhs, delta_c**2)
        return Jacobian, rhs

def spline_get_dxi_dtheta(gr,
                          sim_all,
                          sy_all,
                          measurements,
                          xi,
                          w,
                          w_dot,
                          C,
                          mu,
                          options):
                          
        w = 1/w
        #N = options['numberofInnerParams'][int(gr)-1]
        #delta_c = options['deltac'][int(gr)-1]
        N, delta_c, c_1 = get_spline_domain(sim_all)
        Jacobian_derivative = np.zeros((N,N))
        rhs = np.zeros(2*N)

        for y_k, z_k, y_dot_k in \
                zip(sim_all, measurements, sy_all):
            n=math.ceil((y_k - c_1)/ delta_c) + 1
            if(n>N): n=N+1
            i = n-1 #just the iterator to go over the Jacobian matrix
            #calculate the Jacobian derivative:
            if(n==N+1):
                #print("U SEDAM SAAAAM LEEEEL")
                Jacobian_derivative[i-1][i-1] += 2 * w * delta_c**2
                rhs[i-1] += -2*w_dot*( xi[i-1] - z_k)* delta_c**2
            elif(n<N+1):
                if(n>1): Jacobian_derivative[i][i-1] += 2*w*(y_k - c_1 - (n-2)*delta_c) * (c_1 + (n-1)*delta_c - y_k) 
                Jacobian_derivative[i][i] += 2*w*(y_k - c_1 - (n-2)*delta_c)**2  
                if(n>1): rhs[i] += - 2 * xi[i-1] * w * y_dot_k *(2*c_1 + (2*n-3)*delta_c - 2* y_k) - 2 * xi[i-1] * w_dot * (y_k - c_1 - (n-2)*delta_c) * (c_1 + (n-1)*delta_c - y_k) 
                rhs[i] += - 2 * xi[i] * (2* y_dot_k * w *(y_k- c_1 - (n-2)*delta_c) + w_dot * (y_k - c_1 - (n-2)*delta_c)**2) 
                rhs[i] += 2 * z_k * delta_c * (y_dot_k * w + w_dot * (y_k-c_1 - (n-2)*delta_c)) 
            elif(n>1):
                Jacobian_derivative[i-1][i-1] += 2*w*(c_1 + (n-1)*delta_c - y_k)**2 
                if(n<N+1): Jacobian_derivative[i-1][i] += 2*w*(y_k - c_1 - (n-2)*delta_c) * (c_1 + (n-1)*delta_c - y_k) 
                if(n<N+1): rhs[i-1] += - 2 * xi[i] * w * y_dot_k * (2*c_1 + (2*n-3)*delta_c - 2* y_k) - 2 * xi[i] * w_dot * (y_k - c_1 - (n-2)*delta_c) * (c_1 + (n-1)*delta_c - y_k) 
                rhs[i-1] += - 2 * xi[i-1] * (2 * w * y_dot_k * (y_k - c_1 (n-1)*delta_c) + w_dot * (y_k - c_1 - (n-1)*delta_c)**2) 
                rhs[i-1] += 2 * z_k * delta_c * (- y_dot_k * w + w_dot * (c_1 + (n-1)*delta_c - y_k)) 
            
        
        Jacobian_derivative =  np.divide(Jacobian_derivative, ((delta_c)**2))
        rhs = np.divide(rhs, ((delta_c)**2))

        from scipy.sparse import csc_matrix, linalg

        lhs = np.block([[Jacobian_derivative, C.transpose()],
                       [(mu*C.transpose()).transpose(), np.diag(C.dot(xi))]])
        
        lhs_sp = csc_matrix(lhs)

        dxi_dtheta = linalg.spsolve(lhs_sp, rhs)
        return dxi_dtheta[:N]

def spline_get_mu(Jacobian,
           rhs,
           xi,
           w,
           C):
    from scipy import linalg
    '''
    mu = np.zeros(problem.groups[gr]['num_constr_full'])
    mu_zero_indices = np.array(problem.groups[gr]['C'].dot(xi) - d).nonzero()[0]
    mu_non_zero_indices = np.where(np.array(problem.groups[gr]['C'].dot(xi) - d) == 0)[0]
    A = problem.groups[gr]['C'].transpose()[:, mu_non_zero_indices]
    mu_non_zero = linalg.lstsq(A, -2*res.dot(problem.groups[gr]['W']))[0]
    mu[mu_non_zero_indices] = mu_non_zero
    '''
    rhs_mu = -2 * np.divide(Jacobian.dot(xi) - rhs,w)
    mu = linalg.lstsq(C.transpose(), rhs_mu, lapack_driver='gelsy')
    return mu[0]

def calculate_dxi_dtheta(gr,
                         problem: OptimalScalingProblem,
                         xi,
                         mu,
                         dy_dtheta,
                         res,
                         d,
                         dd_dtheta):
    from scipy.sparse import csc_matrix, linalg

    A = np.block([[2 * problem.groups[gr]['W'], problem.groups[gr]['C'].transpose()],
                  [(mu*problem.groups[gr]['C'].transpose()).transpose(), np.diag(problem.groups[gr]['C'].dot(xi) + d)]])
    A_sp = csc_matrix(A)

    b = np.block(
        [2 * dy_dtheta.dot(problem.groups[gr]['W']) - 2*problem.groups[gr]['Wdot'].dot(res), -mu*dd_dtheta])

    dxi_dtheta = linalg.spsolve(A_sp, b)
    return dxi_dtheta[:problem.groups[gr]['num_inner_params']]


def get_dy_dtheta(gr,
                  problem: OptimalScalingProblem,
                  sy_all):
    return np.block([sy_all, np.zeros(2*problem.groups[gr]['num_categories'])])


def get_mu(gr,
           problem: OptimalScalingProblem,
           xi,
           res,
           d):
    from scipy import linalg
    '''
    mu = np.zeros(problem.groups[gr]['num_constr_full'])
    mu_zero_indices = np.array(problem.groups[gr]['C'].dot(xi) - d).nonzero()[0]
    mu_non_zero_indices = np.where(np.array(problem.groups[gr]['C'].dot(xi) - d) == 0)[0]
    A = problem.groups[gr]['C'].transpose()[:, mu_non_zero_indices]
    mu_non_zero = linalg.lstsq(A, -2*res.dot(problem.groups[gr]['W']))[0]
    mu[mu_non_zero_indices] = mu_non_zero
    '''
    mu = linalg.lstsq(problem.groups[gr]['C'].transpose(), -2*res.dot(problem.groups[gr]['W']), lapack_driver='gelsy')
    return mu[0]


def get_xi(gr,
           problem: OptimalScalingProblem,
           x_inner_opt: Dict,
           sim: List[np.ndarray],
           options: Dict):

    xs = problem.get_xs_for_group(gr)
    interval_range, interval_gap = \
        compute_interval_constraints(xs, sim, options)

    xi = np.zeros(problem.groups[gr]['num_inner_params'])
    surrogate_all, x_lower, x_upper = \
        get_surrogate_all(xs, x_inner_opt['x'], sim, interval_range, interval_gap, options)
    xi[:problem.groups[gr]['num_datapoints']] = surrogate_all.flatten()
    xi[problem.groups[gr]['lb_indices']] = x_lower
    xi[problem.groups[gr]['ub_indices']] = x_upper
    return xi


def optimize_surrogate_data(xs: List[InnerParameter],
                            sim: List[np.ndarray],
                            options: Dict):
    """Run optimization for inner problem"""

    from scipy.optimize import minimize

    interval_range, interval_gap = \
        compute_interval_constraints(xs, sim, options)
    w = get_weight_for_surrogate(xs, sim)

    def obj_surr(x):
        return obj_surrogate_data(xs, x, sim, interval_gap,
                                  interval_range, w, options)

    inner_options = \
        get_inner_options(options, xs, sim, interval_range, interval_gap)
    try:
        results = minimize(obj_surr, **inner_options)
    except:
        print('x0 violate bound constraints. Retrying with array of zeros.')
        inner_options['x0'] = np.zeros(len(inner_options['x0']))
        results = minimize(obj_surr, **inner_options)
    return results


def get_inner_options(options: Dict,
                      xs: List[InnerParameter],
                      sim: List[np.ndarray],
                      interval_range: float,
                      interval_gap: float) -> Dict:

    """Return default options for scipy optimizer"""

    from scipy.optimize import Bounds

    min_all, max_all = get_min_max(xs, sim)
   # print("Evo max", max_all)
    if options['method'] == REDUCED:
        parameter_length = len(xs)
        x0 = np.linspace(
            np.max([min_all, interval_range]),
            max_all + (interval_range + interval_gap)*parameter_length,
            parameter_length
        )
        #print("Min", min_all, "i max", max_all)
        #print("Evo i x0", x0)
    elif options['method'] == STANDARD:
        parameter_length = 2 * len(xs)
        x0 = np.linspace(0, max_all + interval_range, parameter_length)
    else:
        raise NotImplementedError(
            f"Unkown optimal scaling method {options['method']}. "
            f"Please use {STANDARD} or {REDUCED}."

        )

    if options['reparameterized']:
        x0 = y2xi(x0, xs, interval_gap, interval_range)
        bounds = Bounds([0.0] * parameter_length, [max_all + (interval_range + interval_gap)*parameter_length] * parameter_length)
        inner_options = {'x0': x0, 'method': 'L-BFGS-B',
                         'options': {'maxiter': 2000, 'ftol': 1e-10},
                         'bounds': bounds}
    else:
        constraints = get_constraints_for_optimization(xs, sim, options)

        inner_options = {'x0': x0, 'method': 'SLSQP',
                         'options': {'maxiter': 2000, 'ftol': 1e-10, 'disp': True},
                         'constraints': constraints}
    return inner_options


def get_min_max(xs: List[InnerParameter],
                sim: List[np.ndarray]) -> Tuple[float, float]:
    """Return minimal and maximal simulation value"""

    sim_all = get_sim_all(xs, sim)

    min_all = np.min(sim_all)
    max_all = np.max(sim_all)

    return min_all, max_all


def get_sy_all(xs, sy, par_idx):
    sy_all = []
    for x in xs:
        for sy_i, mask_i in \
                zip(sy, x.ixs):
                sim_sy = sy_i[:, par_idx, :][mask_i]
                #if mask_i.any():
                for sim_sy_i in sim_sy:
                    sy_all.append(sim_sy_i)
    return np.array(sy_all)


def get_sim_all(xs, sim: List[np.ndarray]) -> list:
    """"Get list of all simulations for all xs"""

    sim_all = []
    for x in xs:
        for sim_i, mask_i in \
                zip(sim, x.ixs):
            sim_x = sim_i[mask_i]
            #if mask_i.any():
            for sim_x_i in sim_x:
               sim_all.append(sim_x_i)
    #print("Evo sim all: ", sim_all)
    return sim_all

def get_sim_all_for_quantitative(gr, sim: List[np.ndarray], simulation_indices: List) -> list:
    """"Get list of all simulations for quantitative group"""
    
    gr = int(gr)-1
    sim_length=0
    for condition_indx in range(len(simulation_indices[gr])):
        sim_length+= len(simulation_indices[gr][condition_indx])
    sim_all= -np.ones((sim_length))

    current_indx=0
    for condition_indx in range(len(simulation_indices[gr])):
        for time_indx in simulation_indices[gr][condition_indx]:
            sim_all[current_indx] = sim[condition_indx][time_indx][gr]
            current_indx+=1
    
    # print(sim_all)
    # breakpoint()
    
    # gr = int(gr) - 1 # OLD STUFF
    # sim = np.asarray(sim)
    # sim_temp = sim[:, :, gr]
    # # if(gr == 0 or gr == 1.0 or gr == 2.0 or gr == 3.0): #FIEDLEr fix
    # #     sim_all = sim[0][:, gr]
    # # else:
    # #     sim_all = np.block([sim[1][:,gr], sim[2][:,gr]])
    # sim_all = np.zeros(sim_temp.size)
    # for i in range(len(sim_temp)):
    #     for j in range(len(sim_temp[i])):
    #         sim_all[i+j] = sim_temp[i][j]
    return sim_all

def get_sy_all_for_quantitative(gr, sy, par_idx, simulation_indices):
    
    #print(sy)
    gr = int(gr)-1
    sim_length=0
    for condition_indx in range(len(simulation_indices[gr])):
        sim_length+= len(simulation_indices[gr][condition_indx])
    sy_all = -np.ones((sim_length))
    i=0
    current_indx=0
    for condition_indx in range(len(simulation_indices[gr])):
        for time_indx in simulation_indices[gr][condition_indx]:
            sy_all[current_indx] = sy[condition_indx][time_indx][par_idx][gr]
            current_indx+=1
    #print(gr, par_idx, sy_all)
    #breakpoint()
    #OLDSTUFF
    # for sy_i in sy:
        #if(i==0 and (gr == 0 or gr == 1 or gr == 2 or gr == 3)): #Fiedler changes
            # sim_sy = sy_i[:, par_idx, gr]
            # for sim_sy_i in sim_sy:
            #     sy_all.append(sim_sy_i)
        # if((i==1 or i==2) and (gr == 4.0 or gr == 5 or gr == 6 or gr == 7)):
        #     sim_sy = sy_i[:, par_idx, gr]
        #     for sim_sy_i in sim_sy:
        #         sy_all.append(sim_sy_i)
        # i=i+1
    return sy_all

def get_surrogate_all(xs,
                      optimal_scaling_bounds,
                      sim,
                      interval_range,
                      interval_gap,
                      options):
    if options['reparameterized']:
        optimal_scaling_bounds = \
            xi2y(optimal_scaling_bounds, xs, interval_gap, interval_range)
    surrogate_all = []
    x_lower_all = []
    x_upper_all = []
    for x in xs:
        x_upper, x_lower = \
            get_bounds_for_category(
                x, optimal_scaling_bounds, interval_gap, options
            )
        #print("Upper:", x_upper, "\n lower:", x_lower)
        for sim_i, mask_i in \
                zip(sim, x.ixs):
            #if mask_i.any():
                y_sim = sim_i[mask_i]
                for y_sim_i in y_sim:
                    if x_lower > y_sim_i:
                        y_surrogate = x_lower
                    elif y_sim_i > x_upper:
                        y_surrogate = x_upper
                    elif x_lower <= y_sim_i <= x_upper:
                        y_surrogate = y_sim_i
                    else:
                        continue
                    surrogate_all.append(y_surrogate)
        x_lower_all.append(x_lower)
        x_upper_all.append(x_upper)
    return np.array(surrogate_all), np.array(x_lower_all), np.array(x_upper_all)


def get_weight_for_surrogate(xs: List[InnerParameter],
                             sim: List[np.ndarray]) -> float:
    """Calculate weights for objective function"""

    sim_x_all = get_sim_all(xs, sim)
    eps = 1e-8
   # v_net = 0
   # for idx in range(len(sim_x_all) - 1):
   #     v_net += np.abs(sim_x_all[idx + 1] - sim_x_all[idx])
   # w = 0.5 * np.sum(np.abs(sim_x_all)) + v_net + eps
    # print(w ** 2)
    return np.sum(np.abs(sim_x_all)) + eps  # TODO: w ** 2


def compute_interval_constraints(xs: List[InnerParameter],
                                 sim: List[np.ndarray],
                                 options: Dict) -> Tuple[float, float]:
    """Compute minimal interval range and gap"""

    # compute constraints on interval size and interval gap size
    # similar to Pargett et al. (2014)
    if 'minGap' not in options:
        eps = 1e-16
    else:
        eps = options['minGap']

    min_simulation, max_simulation = get_min_max(xs, sim)

    if options['intervalConstraints'] == MAXMIN:

        interval_range = \
            (max_simulation - min_simulation) / (2 * len(xs) + 1)
        interval_gap = \
            (max_simulation - min_simulation) / (4 * (len(xs) - 1) + 1)
    elif options['intervalConstraints'] == MAX:

        interval_range = max_simulation / (2 * len(xs) + 1)
        interval_gap = max_simulation / (4 * (len(xs) - 1) + 1)
    else:
        raise ValueError(
            f"intervalConstraints = "
            f"{options['intervalConstraints']} not implemented. "
            f"Please use {MAX} or {MAXMIN}."

        )
    #if interval_gap < eps:
    #    interval_gap = eps
    return interval_range, interval_gap + eps


def y2xi(optimal_scaling_bounds: np.ndarray,
         xs: List[InnerParameter],
         interval_gap: float,
         interval_range: float) -> np.ndarray:
    """Get optimal scaling bounds and return reparameterized parameters"""

    optimal_scaling_bounds_reparameterized = \
        np.full(shape=(np.shape(optimal_scaling_bounds)), fill_value=np.nan)

    for x in xs:
        x_category = int(x.category)
        if x_category == 1:
            optimal_scaling_bounds_reparameterized[x_category - 1] = \
                optimal_scaling_bounds[x_category - 1] \
                - interval_range
        else:
            optimal_scaling_bounds_reparameterized[x_category - 1] = \
                optimal_scaling_bounds[x_category - 1] \
                - optimal_scaling_bounds[x_category - 2] \
                - interval_gap - interval_range

    return optimal_scaling_bounds_reparameterized


def xi2y(
        optimal_scaling_bounds_reparameterized: np.ndarray,
        xs: List[InnerParameter],
        interval_gap: float,
        interval_range: float) -> np.ndarray:
    """
    Get reparameterized parameters and
    return original optimal scaling bounds
    """

    # TODO: optimal scaling parameters in
    #  parameter sheet have to be ordered at the moment
    optimal_scaling_bounds = \
        np.full(shape=(np.shape(optimal_scaling_bounds_reparameterized)),
                fill_value=np.nan)
    for x in xs:
        x_category = int(x.category)
        if x_category == 1:
            optimal_scaling_bounds[x_category - 1] = \
                interval_range + optimal_scaling_bounds_reparameterized[
                    x_category - 1]
        else:
            optimal_scaling_bounds[x_category - 1] = \
                optimal_scaling_bounds_reparameterized[x_category - 1] + \
                interval_gap + interval_range + optimal_scaling_bounds[
                    x_category - 2]
    return optimal_scaling_bounds


def obj_surrogate_data(xs: List[InnerParameter],
                       optimal_scaling_bounds: np.ndarray,
                       sim: List[np.ndarray],
                       interval_gap: float,
                       interval_range: float,
                       w: float,
                       options: Dict) -> float:
    """compute optimal scaling objective function"""

    obj = 0.0
    if options['reparameterized']:
        optimal_scaling_bounds = \
            xi2y(optimal_scaling_bounds, xs, interval_gap, interval_range)

    for x in xs:
        x_upper, x_lower = \
            get_bounds_for_category(
                x, optimal_scaling_bounds, interval_gap, options
            )
        for sim_i, mask_i in \
                zip(sim, x.ixs):
            #if mask_i.any():
                y_sim = sim_i[mask_i]
                for y_sim_i in y_sim:
                    if x_lower > y_sim_i:
                        y_surrogate = x_lower
                    elif y_sim_i > x_upper:
                        y_surrogate = x_upper
                    elif x_lower <= y_sim_i <= x_upper:
                        y_surrogate = y_sim_i
                    else:
                        continue
                    obj += (y_surrogate - y_sim_i) ** 2
    obj = np.divide(obj, w)
   # print("Evo objective:", obj)
    return obj


def get_bounds_for_category(x: InnerParameter,
                            optimal_scaling_bounds: np.ndarray,
                            interval_gap: float,
                            options: Dict) -> Tuple[float, float]:
    """Return upper and lower bound for a specific category x"""

    x_category = int(x.category)

    if options['method'] == REDUCED:
        x_upper = optimal_scaling_bounds[x_category - 1]
        if x_category == 1:
            x_lower = 0
        elif x_category > 1:
            x_lower = optimal_scaling_bounds[x_category - 2] + 0.5 * interval_gap
        else:
            raise ValueError('Category value needs to be larger than 0.')
    elif options['method'] == STANDARD:
        x_lower = optimal_scaling_bounds[2 * x_category - 2]
        x_upper = optimal_scaling_bounds[2 * x_category - 1]
    else:
        raise NotImplementedError(
            f"Unkown optimal scaling method {options['method']}. "
            f"Please use {REDUCED} or {STANDARD}."

        )
    return x_upper, x_lower


def get_constraints_for_optimization(xs: List[InnerParameter],
                                     sim: List[np.ndarray],
                                     options: Dict) -> Dict:
    """Return constraints for inner optimization"""

    num_categories = len(xs)
    interval_range, interval_gap = \
        compute_interval_constraints(xs, sim, options)
    if options['method'] == REDUCED:
        a = np.diag(-np.ones(num_categories), -1) \
            + np.diag(np.ones(num_categories + 1))
        a = a[:-1, :-1]
        b = np.empty((num_categories,))
        b[0] = interval_range
        b[1:] = interval_range + interval_gap
    elif options['method'] == STANDARD:
        a = np.diag(-np.ones(2 * num_categories), -1) \
            + np.diag(np.ones(2 * num_categories + 1))
        a = a[:-1, :]
        a = a[:, :-1]
        b = np.empty((2 * num_categories,))
        b[0] = 0
        b[1::2] = interval_range
        b[2::2] = interval_gap
    ineq_cons = {'type': 'ineq', 'fun': lambda x: a.dot(x) - b}

    return ineq_cons

def calculate_obj_fun_for_hard_constraints(xs: List[InnerParameter],
                                           sim: List[np.ndarray],
                                           options: Dict,
                                           hard_constraints: pd.DataFrame):

    interval_range, interval_gap = \
        compute_interval_constraints(xs, sim, options)
    w = get_weight_for_surrogate(xs, sim)

    obj = 0.0

    parameter_length = len(xs)
    min_all, max_all = get_min_max(xs, sim)
    max_upper = max_all + (interval_range + interval_gap)*parameter_length

    for x in xs:
        x_upper, x_lower = \
            get_bounds_from_hard_constraints(
                x, hard_constraints, max_upper, interval_gap
            )
        for sim_i, mask_i in \
                zip(sim, x.ixs):
            #if mask_i.any():
                y_sim = sim_i[mask_i]
                for y_sim_i in y_sim:
                    if x_lower > y_sim_i:
                        y_surrogate = x_lower
                    elif y_sim_i > x_upper:
                        y_surrogate = x_upper
                    elif x_lower <= y_sim_i <= x_upper:
                        y_surrogate = y_sim_i
                    else:
                        continue
                    obj += (y_surrogate - y_sim_i) ** 2
    obj = np.divide(obj, w)
    return obj

def get_bounds_from_hard_constraints(x: InnerParameter,
                                    hard_constraints: pd.DataFrame,
                                    max_upper: float,
                                    interval_gap: float) -> Tuple[float, float]:
    x_category = int(x.category)
    
    constraint = hard_constraints[hard_constraints['category']==x_category]
    lower_constraint=-1
    upper_constraint=-1
    measurement = constraint['measurement'].values[0]
    measurement = measurement.replace(" ", "")
    
    if('<' in measurement and '>' in measurement):
        lower_constraint = float(measurement.split(',')[0][1:])
        upper_constraint = float(measurement.split(',')[1][1:])
    elif('<' in measurement):
        upper_constraint = float(measurement[1:])
    elif('>' in measurement):
        lower_constraint = float(measurement[1:])
    #print("bounds point", x_category, measurement, lower_constraint, upper_constraint)
    if(upper_constraint == -1):
        x_upper = max_upper
    else:
        x_upper = upper_constraint
    
    if(lower_constraint!=-1 ):
        #print("lower constraint in action")
        x_lower=lower_constraint + 1e-6
    elif(x_category == 1):
        #print("no lower constraint")
        x_lower = 0 

    return x_upper, x_lower

def get_xi_for_hard_constraints(gr,
                                problem: OptimalScalingProblem,
                                hard_constraints: pd.DataFrame,
                                sim: List[np.ndarray],
                                options: Dict):
    xs = problem.get_xs_for_group(gr)
    interval_range, interval_gap = \
        compute_interval_constraints(xs, sim, options)

    parameter_length = len(xs)
    min_all, max_all = get_min_max(xs, sim)
    max_upper = max_all + (interval_range + interval_gap)*parameter_length

    xi = np.zeros(problem.groups[gr]['num_inner_params'])
    surrogate_all = []
    x_lower_all = []
    x_upper_all = []
    for x in xs:
        x_upper, x_lower = \
            get_bounds_from_hard_constraints(
                x, hard_constraints, max_upper, interval_gap
            )
        for sim_i, mask_i in \
                zip(sim, x.ixs):
            #if mask_i.any():
                y_sim = sim_i[mask_i]
                for y_sim_i in y_sim:
                    if x_lower > y_sim_i:
                        y_surrogate = x_lower
                    elif y_sim_i > x_upper:
                        y_surrogate = x_upper
                    elif x_lower <= y_sim_i <= x_upper:
                        y_surrogate = y_sim_i
                    else:
                        continue
                    surrogate_all.append(y_surrogate)
                    #print("GLE OVO ", x.category ,y_surrogate, x_lower, x_upper)
        x_lower_all.append(x_lower)
        x_upper_all.append(x_upper)
    
    xi[:problem.groups[gr]['num_datapoints']] = np.array(surrogate_all).flatten()
    xi[problem.groups[gr]['lb_indices']] = np.array(x_lower_all)
    xi[problem.groups[gr]['ub_indices']] = np.array(x_upper_all)
    return xi

def get_spline_domain(sim_all):
    K = len(sim_all)

    min_all=max_all=sim_all[0]
    for s in sim_all:
        if(s>max_all): max_all = s
        if(s<min_all): min_all = s    
    range_all = max_all - min_all

    if(min_all - range_all/(math.ceil(K/2)-2) < 0):
        N = math.floor(K/2)
        delta_c = max_all/(N-1/2)
        c_1 = delta_c
    else:
        N = math.ceil(K/2)
        delta_c = range_all/(N-2)
        c_1 = min_all - 0.5*delta_c
    #print("spline domain: \n", sim_all)
    #print(N, delta_c, c_1)
    #print(min_all, 0.1*range_all)
    return N, delta_c, c_1
    
