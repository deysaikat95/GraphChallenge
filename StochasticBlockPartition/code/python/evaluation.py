"""Module containing the Evaluation class, which stores evaluation results and saves them to file.
"""

import os
import csv

from typing import List, Dict
from argparse import Namespace

import numpy as np
from scipy.spatial.distance import jensenshannon

from graph import Graph
from sample import Sample
from mcmc_timings import MCMCTimings
from block_merge_timings import BlockMergeTimings


class Evaluation(object):
    """Stores the evaluation results, and saves them to file.
    """

    FIELD_NAMES = [
        'block size variation',
        'block overlap',
        'streaming type',
        'num vertices',
        'num edges',
        'blocks retained (%)',
        'within to between edge ratio',
        'difference from ideal sample',
        'expansion quality',
        'subgraph clustering coefficient',
        'full graph clustering coefficient',
        'subgraph within to between edge ratio',
        'subgraph num blocks in algorithm partition',
        'subgraph num blocks in truth partition',
        'subgraph accuracy',
        'subgraph rand index',
        'subgraph adjusted rand index',
        'subgraph pairwise recall',
        'subgraph pairwise precision',
        'subgraph entropy of algorithm partition',
        'subgraph entropy of truth partition',
        'subgraph entropy of algorithm partition given truth partition',
        'subgraph entropy of truth partition given algorithm partition',
        'subgraph mutual information',
        'subgraph fraction of missed information',
        'subgraph fraction of erroneous information',
        'jensen_shannon_divergence',
        'random_jensen_shannon_divergence',
        'num block proposals',
        'beta',
        'sample size (%)',
        'sampling iterations',
        'sampling algorithm',
        'sparse',
        'delta entropy threshold',
        'nodal update threshold strategy',
        'nodal update threshold factor',
        'nodal update threshold direction',
        'num blocks in algorithm partition',
        'num blocks in truth partition',
        'accuracy',
        'rand index',
        'adjusted rand index',
        'pairwise recall',
        'pairwise precision',
        'entropy of algorithm partition',
        'entropy of truth partition',
        'entropy of algorithm partition given truth partition',
        'entropy of truth partition given algorithm partition',
        'mutual information',
        'fraction of missed information',
        'fraction of erroneous information',
        'num nodal updates',
        'num nodal update iterations',
        'num finetuning updates',
        'num finetuning iterations',
        'num iterations',
        'graph loading time',
        'sampling time',
        'total partition time',
        'total nodal update time',
        'total block merge time',
        'prepare the next iteration',
        'merging partitioned sample time',
        'cluster propagation time',
        'finetuning membership time'
    ]

    DETAILS_FIELD_NAMES = [
        'superstep',
        'step',
        'iteration',
        'substep',
        'time'
    ]

    def __init__(self, args: Namespace, graph: Graph) -> None:
        """Creates a new Evaluation object.

            Parameters
            ----------
            args : Namespace
                the command-line arguments
            graph : Graph
                the loaded graph to be partitioned
        """
        # CSV file into which to write the results
        self.csv_file = args.csv + ".csv"
        self.csv_details_file = args.csv + "_details.csv"
        self.args = args
        # Dataset parameters
        self.block_size_variation = args.blockSizeVar
        self.block_overlap = args.overlap
        self.streaming_type = args.type
        self.num_nodes = graph.num_nodes
        self.num_edges = graph.num_edges
        # Sampling evaluation
        self.blocks_retained = 0.0
        self.graph_edge_ratio = 0.0
        self.difference_from_ideal_sample = 0.0
        self.expansion_quality = 0.0
        self.subgraph_clustering_coefficient = 0.0
        self.full_graph_clustering_coefficient = 0.0
        self.subgraph_edge_ratio = 0.0
        self.subgraph_num_blocks_algorithm = 0
        self.subgraph_num_blocks_truth = 0
        self.subgraph_accuracy = 0.0
        self.subgraph_rand_index = 0.0
        self.subgraph_adjusted_rand_index = 0.0
        self.subgraph_pairwise_recall = 0.0
        self.subgraph_pairwise_precision = 0.0
        self.subgraph_entropy_algorithm = 0.0
        self.subgraph_entropy_truth = 0.0
        self.subgraph_entropy_algorithm_given_truth = 0.0
        self.subgraph_entropy_truth_given_algorithm = 0.0
        self.subgraph_mutual_info = 0.0
        self.subgraph_missed_info = 0.0
        self.subgraph_erroneous_info = 0.0
        self.jensen_shannon_divergence = 0.0
        self.random_jensen_shannon_divergence = 0.0
        # Algorithm parameters
        self.num_block_proposals = args.blockProposals
        self.beta = args.beta
        self.sample_size = args.sample_size
        self.sampling_iterations = args.sample_iterations
        self.sampling_algorithm = args.sample_type
        self.sparse = args.sparse
        self.delta_entropy_threshold = args.threshold
        self.nodal_update_threshold_strategy = args.nodal_update_strategy
        self.nodal_update_threshold_factor = args.factor
        self.nodal_update_threshold_direction = args.direction
        # Goodness of partition measures
        self.num_blocks_algorithm = 0
        self.num_blocks_truth = 0
        self.accuracy = 0.0
        self.rand_index = 0.0
        self.adjusted_rand_index = 0.0
        self.pairwise_recall = 0.0
        self.pairwise_precision = 0.0
        self.entropy_algorithm = 0.0
        self.entropy_truth = 0.0
        self.entropy_algorithm_given_truth = 0.0
        self.entropy_truth_given_algorithm = 0.0
        self.mutual_info = 0.0
        self.missed_info = 0.0
        self.erroneous_info = 0.0
        # Algorithm runtime measures
        self.num_nodal_updates = 0
        self.num_nodal_update_iterations = 0
        self.num_finetuning_updates = 0
        self.num_finetuning_iterations = 0
        self.num_iterations = 0
        self.loading = 0.0
        self.sampling = 0.0
        self.total_partition_time = 0.0
        self.total_block_merge_time = 0.0
        self.total_nodal_update_time = 0.0
        self.prepare_next_partition = 0.0
        self.merge_sample = 0.0
        self.propagate_membership = 0.0
        self.finetune_membership = 0.0
        self.prepare_next_partitions = list()  # type: List[float]
        self.mcmc_details = list()  # type: List[MCMCTimings]
        self.block_merge_details = list()  # type: List[BlockMergeTimings]
        self.finetuning_details = None
    # End of __init__()

    def evaluate_subgraph_sampling(self, full_graph: Graph, subgraph: Graph, full_partition: 'partition.Partition',
        subgraph_partition: 'partition.Partition', sample: Sample):
        """Evaluates the goodness of the samples returned by the subgraph.

        Parameters
        ----------
        full_graph : Graph
            the full, unsampled Graph object
        subgraph : Graph
            the sampled subgraph
        full_partition : Partition
            the partitioning results on the full graph
        subgraph_partition : Partition
            the partitioning results on the sampled subgraph
        block_mapping : Dict[int, int]
            the mapping of blocks from the full graph to the subgraph
        vertex_mapping : Dict[int, int]
            the mapping of vertices from the full graph to the subgraph
        """
        #####
        # % of communities retained
        #####
        full_graph_num_blocks = len(np.unique(full_graph.true_block_assignment))
        subgraph_num_blocks = len(np.unique(subgraph.true_block_assignment))

        self.blocks_retained = subgraph_num_blocks / full_graph_num_blocks

        #####
        # % difference in ratio of within-block to between-block edges
        #####
        true_subgraph_partition = subgraph_partition.clone_with_true_block_membership(subgraph.out_neighbors,
                                                                                      subgraph.true_block_assignment)
        subgraph_blockmatrix = true_subgraph_partition.interblock_edge_count
        self.subgraph_edge_ratio = subgraph_blockmatrix.trace() / subgraph_blockmatrix.sum()
        true_full_partition = full_partition.clone_with_true_block_membership(full_graph.out_neighbors,
                                                                              full_graph.true_block_assignment)
        full_blockmatrix = true_full_partition.interblock_edge_count
        self.graph_edge_ratio = full_blockmatrix.trace() / full_blockmatrix.sum()

        #####
        # Shannon divergence between partitions
        #####
        self.jensen_shannon_divergence = self.truth_divergence(
            full_graph, sample, true_full_partition, subgraph_partition
        )
        self.random_jensen_shannon_divergence = self.random_divergence(
            full_graph, sample, full_partition, subgraph_partition
        )

        #####
        # Normalized difference from ideal-block membership
        #####
        full_graph_membership_nums = np.zeros(full_graph_num_blocks)
        for block_membership in full_graph.true_block_assignment:
            full_graph_membership_nums[block_membership] += 1
        subgraph_membership_nums = np.zeros(full_graph_num_blocks)
        # invert dict to map subgraph block id to full graph block id
        true_block_mapping = dict([(v, k) for k, v in sample.true_blocks_mapping.items()])
        for block_membership in subgraph.true_block_assignment:
            subgraph_membership_nums[true_block_mapping[block_membership]] += 1
        ideal_block_membership_nums = full_graph_membership_nums * (subgraph.num_nodes / full_graph.num_nodes)
        difference_from_ideal_block_membership_nums = np.abs(ideal_block_membership_nums - subgraph_membership_nums)
        self.difference_from_ideal_sample = np.sum(difference_from_ideal_block_membership_nums / subgraph.num_nodes)

        ######
        # Expansion quality (http://portal.acm.org/citation.cfm?doid=1772690.1772762)
        ######
        # Expansion factor = Neighbors of sample / size of sample
        # Maximum expansion factor = (size of graph - size of sample) / size of sample
        # Expansion quality = Neighbors of sample / (size of graph - size of sample)
        # Expansion quality = 1 means sample is at most 1 edge away from entire graph
        subgraph_vertices = set(sample.vertex_mapping.keys())
        neighbors = set()
        for vertex in subgraph_vertices:
            for neighbor in full_graph.out_neighbors[vertex]:
                neighbors.add(neighbor[0])
        neighbors = neighbors - subgraph_vertices
        self.expansion_quality = len(neighbors) / (full_graph.num_nodes - subgraph.num_nodes)

        ######
        # Clustering coefficient
        ######
        self.subgraph_clustering_coefficient = self.clustering_coefficient(subgraph)
        self.full_graph_clustering_coefficient = self.clustering_coefficient(full_graph)
    # End of evaluate_subgraph_sampling()

    def update_timings(self, block_merge_start_t: float, node_update_start_t: float, prepare_next_start_t: float,
        prepare_next_end_t: float):
        """Updates the timings of a single iteration (block merge + nodal updates)

            Parameters
            ---------
            block_merge_start_t : float
                the start time of the block merge step
            node_update_start_t : float
                the start time of the nodal update step
            prepare_next_start_t : float
                the start time for preparing for the next partitioning iteration
            prepare_next_end_t : float
                the end time for preparing for the next partitioning iterations
        """
        block_merge_t = node_update_start_t - block_merge_start_t
        node_update_t = prepare_next_start_t - node_update_start_t
        prepare_next_t = prepare_next_end_t - prepare_next_start_t
        self.total_block_merge_time += block_merge_t
        self.total_nodal_update_time += node_update_t
        self.prepare_next_partition += prepare_next_t
        self.prepare_next_partitions.append(prepare_next_t)
    # End of update_timings()

    def total_runtime(self, start_t: float, end_t: float):
        """Finalizes the runtime of the algorithm.

            Parameters
            ---------
            start_t : float
                the start time of the partitioning
            end_t : float
                the end time of the partitioning
        """
        runtime = end_t - start_t
        self.total_partition_time = runtime
    # End of total_runtime()

    def clustering_coefficient(self, graph: Graph) -> float:
        """Calculates the clustering coefficient of a given graph.

        Clustering coefficient = number of closed triangles / total possible number of triangles.

        Current version also counts self-connections as triangles as well.

            Parameters
            ---------
            graph : Graph
                the graph whose clustering coefficient is of interest
            
            Returns
            -------
            clustering_coefficient : float
                the clustering coefficient of said graph
        """
        n_triangles_sample = 0
        for vertex in range(graph.num_nodes):
            for neighbor in graph.out_neighbors[vertex]:
                for neighbor2 in graph.out_neighbors[vertex]:
                    # TODO: If not counting self-links, add check for that here
                    if neighbor2[0] in graph.out_neighbors[neighbor[0]]:
                        n_triangles_sample += 1
        return n_triangles_sample / (graph.num_nodes * (graph.num_nodes - 1))
    # End of clustering_coefficient()

    def save(self):
        """Saves the evaluation to a CSV file. Creates a new CSV file one the path of csv_file doesn't exist. Appends
        results to the CSV file if it does.
        """
        write_header = False
        if not os.path.isfile(self.csv_file):
            directory = os.path.dirname(self.csv_file)
            if directory not in [".", ""]:
                os.makedirs(directory, exist_ok=True)
            write_header = True
        with open(self.csv_file, "a") as csv_file:
            writer = csv.writer(csv_file)
            if write_header:
                writer.writerow(Evaluation.FIELD_NAMES)
            writer.writerow([
                self.block_size_variation,
                self.block_overlap,
                self.streaming_type,
                self.num_nodes,
                self.num_edges,
                self.blocks_retained,
                self.graph_edge_ratio,
                self.difference_from_ideal_sample,
                self.expansion_quality,
                self.subgraph_clustering_coefficient,
                self.full_graph_clustering_coefficient,
                self.subgraph_edge_ratio,
                self.subgraph_num_blocks_algorithm,
                self.subgraph_num_blocks_truth,
                self.subgraph_accuracy,
                self.subgraph_rand_index,
                self.subgraph_adjusted_rand_index,
                self.subgraph_pairwise_recall,
                self.subgraph_pairwise_precision,
                self.subgraph_entropy_algorithm,
                self.subgraph_entropy_truth,
                self.subgraph_entropy_algorithm_given_truth,
                self.subgraph_entropy_truth_given_algorithm,
                self.subgraph_mutual_info,
                self.subgraph_missed_info,
                self.subgraph_erroneous_info,
                self.jensen_shannon_divergence,
                self.random_jensen_shannon_divergence,
                self.num_block_proposals,
                self.beta,
                self.sample_size,
                self.sampling_iterations,
                self.sampling_algorithm,
                self.sparse,
                self.delta_entropy_threshold,
                self.nodal_update_threshold_strategy,
                self.nodal_update_threshold_factor,
                self.nodal_update_threshold_direction,
                self.num_blocks_algorithm,
                self.num_blocks_truth,
                self.accuracy,
                self.rand_index,
                self.adjusted_rand_index,
                self.pairwise_recall,
                self.pairwise_precision,
                self.entropy_algorithm,
                self.entropy_truth,
                self.entropy_algorithm_given_truth,
                self.entropy_truth_given_algorithm,
                self.mutual_info,
                self.missed_info,
                self.erroneous_info,
                self.num_nodal_updates,
                self.num_nodal_update_iterations,
                self.num_finetuning_updates,
                self.num_finetuning_iterations,
                self.num_iterations,
                self.loading,
                self.sampling,
                self.total_partition_time,
                self.total_nodal_update_time,
                self.total_block_merge_time,
                self.prepare_next_partition,
                self.merge_sample,
                self.propagate_membership,
                self.finetune_membership
            ])
        self._save_details()
    # End of save()

    def _save_details(self):
        """Saves the details of the MCMC and Block Merge timings.
        """
        write_header = False
        if not os.path.isfile(self.csv_details_file):
            directory = os.path.dirname(self.csv_details_file)
            if directory not in [".", ""]:
                os.makedirs(directory, exist_ok=True)
            write_header = True
        with open(self.csv_details_file, "a") as details_file:
            writer = csv.writer(details_file)
            if write_header:
                writer.writerow(Evaluation.DETAILS_FIELD_NAMES)
            for i in range(len(self.mcmc_details)):
                self.mcmc_details[i].save(writer)
                writer.writerow([i, "Preparing for Next Iteration", -1, "-", self.prepare_next_partitions[i]])
            for i in range(len(self.block_merge_details)):
                self.block_merge_details[i].save(writer)
            if self.finetuning_details is not None:
                self.finetuning_details.save(writer)
    # End of _save_details()

    def add_mcmc_timings(self) -> "MCMCTimings":
        """Adds an empty MCMCTimings object to self.mcmc_details

            Returns
            -------
            mcmc_timings : MCMCTimings
                the empty MCMCTimings object
        """
        mcmc_timings = MCMCTimings(len(self.mcmc_details))
        self.mcmc_details.append(mcmc_timings)
        return mcmc_timings
    # End of add_mcmc_timings()

    def add_finetuning_timings(self) -> "MCMCTimings":
        """Adds an empty MCMCTimings object to self.mcmc_details

            Returns
            -------
            finetuning_details : MCMCTimings
                the empty MCMCTimings object
        """
        self.finetuning_details = MCMCTimings(len(self.mcmc_details), "Finetuning Updates")
        return self.finetuning_details
    # End of add_mcmc_timings()

    def add_block_merge_timings(self) -> "BlockMergeTimings":
        """Adds an empty BlockMergeTimings object to self.block_merge_details

            Returns
            -------
            block_merge_timings : BlockMergeTimings
                the empty BlockMergeTimings object
        """
        block_merge_timings = BlockMergeTimings(len(self.block_merge_details))
        self.block_merge_details.append(block_merge_timings)
        return block_merge_timings
    # End of add_block_merge_timings()

    def truth_divergence(self, graph: Graph, sample: Sample, true_partition: 'partition.Partition',
        sample_graph_partition: 'partition.Partition') -> float:
        """Shannon distance between the true full graph and true sampled subgraph blockmodels.
        """
        true_b = graph.true_block_assignment
        sample_b = true_b[sample.state.sample_idx]
        sample_out_neighbors = list()  # type: List[np.ndarray]
        # print("Sampled IDs: ", sample.state.sample_idx)
        for i in range(len(graph.out_neighbors)):
            if i not in sample.state.sample_idx:
                sample_out_neighbors.append(np.asarray([[]]))
            else:
                neighbors = graph.out_neighbors[i]
                sampled = list()
                for i in range(len(neighbors)):
                    neighbor = neighbors[i]
                    if neighbor[0] in sample.state.sample_idx:
                        sampled.append(i)
                sample_out_neighbors.append(neighbors[sampled])
        true_sample_partition = sample_graph_partition.clone_with_true_block_membership(sample_out_neighbors, true_b)
        true_blockmodel = true_partition.interblock_edge_count.ravel()
        true_sample_blockmodel = true_sample_partition.interblock_edge_count.ravel()
        true_distribution = true_blockmodel / true_blockmodel.sum()
        true_sample_distribution = true_sample_blockmodel / true_sample_blockmodel.sum()
        distance = jensenshannon(true_distribution, true_sample_distribution)
        return distance ** 2
    # End of truth_divergence()

    def random_divergence(self, graph: Graph, sample: Sample, full_graph_partition: 'partition.Partition',
        sample_graph_partition: 'partition.Partition') -> float:
        """Shannon distance between the randomly generated full graph and subgraph blockmodels.
        """
        true_b = np.random.randint(0, int(graph.num_nodes / (100 * np.log(graph.num_nodes))), graph.num_nodes) 
        # sample_b = true_b[sample.state.sample_idx]
        sample_out_neighbors = list()  # type: List[np.ndarray]
        # print("Sampled IDs: ", sample.state.sample_idx)
        for i in range(len(graph.out_neighbors)):
            if i not in sample.state.sample_idx:
                sample_out_neighbors.append(np.asarray([[]]))
            else:
                neighbors = graph.out_neighbors[i]
                sampled = list()
                for i in range(len(neighbors)):
                    neighbor = neighbors[i]
                    if neighbor[0] in sample.state.sample_idx:
                        sampled.append(i)
                sample_out_neighbors.append(neighbors[sampled])
        true_partition = full_graph_partition.clone_with_true_block_membership(graph.out_neighbors, true_b)
        true_sample_partition = sample_graph_partition.clone_with_true_block_membership(sample_out_neighbors, true_b)
        true_blockmodel = true_partition.interblock_edge_count.ravel()
        true_sample_blockmodel = true_sample_partition.interblock_edge_count.ravel()
        true_distribution = true_blockmodel / true_blockmodel.sum()
        true_sample_distribution = true_sample_blockmodel / true_sample_blockmodel.sum()
        distance = jensenshannon(true_distribution, true_sample_distribution)
        return distance ** 2
    # End of truth_divergence()
# End of Evaluation()
