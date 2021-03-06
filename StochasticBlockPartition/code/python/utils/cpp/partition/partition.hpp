/***
 * Stores the current graph partitioning results.
 */
#ifndef CPPSBP_PARTITION_HPP
#define CPPSBP_PARTITION_HPP

#include <iostream>
#include <limits>

#include <Eigen/Core>
#include <pybind11/eigen.h>
#include <pybind11/stl.h>

#include "sparse/boost_mapped_matrix.hpp"

namespace py = pybind11;

typedef py::EigenDRef<Eigen::Matrix<int, Eigen::Dynamic, 2>> Matrix2Column;

typedef struct edge_count_updates_t {
    Vector block_row;
    Vector proposal_row;
    Vector block_col;
    Vector proposal_col;
} EdgeCountUpdates;

class Partition {
  public:
    Partition() : empty(true) {}
    Partition(int num_blocks, float block_reduction_rate) : empty(false) {
        this->num_blocks = num_blocks;
        this->block_reduction_rate = block_reduction_rate;
        this->overall_entropy = std::numeric_limits<float>::max();
        this->blockmodel = BoostMappedMatrix(this->num_blocks, this->num_blocks);
        // Set the block assignment
        this->block_assignment = Vector::LinSpaced(this->num_blocks, 0, this->num_blocks - 1);
        // Number of blocks to merge
        this->num_blocks_to_merge = (int)(this->num_blocks * this->block_reduction_rate);
    }
    Partition(int num_blocks, std::vector<Matrix2Column> &out_neighbors, float block_reduction_rate)
        : Partition(num_blocks, block_reduction_rate) {
        this->initialize_edge_counts(out_neighbors);
    }
    Partition(int num_blocks, std::vector<Matrix2Column> &out_neighbors, float block_reduction_rate,
              Vector &block_assignment)
        : Partition(num_blocks, block_reduction_rate) {
        // Set the block assignment
        this->block_assignment = block_assignment;
        // Number of blocks to merge
        this->initialize_edge_counts(out_neighbors);
    }
    void carry_out_best_merges(Eigen::VectorXd &delta_entropy_for_each_block, Vector &best_merge_for_each_block);
    Partition clone_with_true_block_membership(std::vector<Matrix2Column> &neighbors, Vector &true_block_membership);
    Partition copy();
    // TODO: move block_reduction_rate to some constants file
    static Partition from_sample(int num_blocks, std::vector<Matrix2Column> &neighbors, Vector &sample_block_membership,
                                 std::map<int, int> &mapping, float block_reduction_rate);
    void initialize_edge_counts(std::vector<Matrix2Column> &neighbors);
    double log_posterior_probability();
    void merge_blocks(int from_block, int to_block);
    void move_vertex(int vertex, int current_block, int new_block, EdgeCountUpdates &updates,
                     Vector &new_block_degrees_out, Vector &new_block_degrees_in, Vector &new_block_degrees);
    void set_block_membership(int vertex, int block);
    void update_edge_counts(int current_block, int proposed_block, EdgeCountUpdates &updates);
    BoostMappedMatrix &getBlockmodel() { return this->blockmodel; }
    void setBlockmodel(BoostMappedMatrix blockmodel) { this->blockmodel = blockmodel; }
    Vector &getBlock_assignment() { return this->block_assignment; }
    void setBlock_assignment(Vector block_assignment) { this->block_assignment = block_assignment; }
    Vector &getBlock_degrees() { return this->block_degrees; }
    void setBlock_degrees(Vector block_degrees) { this->block_degrees = block_degrees; }
    Vector &getBlock_degrees_in() { return this->block_degrees_in; }
    void setBlock_degrees_in(Vector block_degrees_in) { this->block_degrees_in = block_degrees_in; }
    Vector &getBlock_degrees_out() { return this->block_degrees_out; }
    void setBlock_degrees_out(Vector block_degrees_out) { this->block_degrees_out = block_degrees_out; }
    float &getBlock_reduction_rate() { return this->block_reduction_rate; }
    void setBlock_reduction_rate(float block_reduction_rate) { this->block_reduction_rate = block_reduction_rate; }
    float &getOverall_entropy() { return this->overall_entropy; }
    void setOverall_entropy(float overall_entropy) { this->overall_entropy = overall_entropy; }
    int &getNum_blocks_to_merge() { return this->num_blocks_to_merge; }
    void setNum_blocks_to_merge(int num_blocks_to_merge) { this->num_blocks_to_merge = num_blocks_to_merge; }
    int &getNum_blocks() { return this->num_blocks; }
    void setNum_blocks(int num_blocks) { this->num_blocks = num_blocks; }
    // Other
    bool empty;

  private:
    // Structure
    int num_blocks;
    BoostMappedMatrix blockmodel;
    // Known info
    Vector block_assignment;
    Vector block_degrees;
    Vector block_degrees_in;
    Vector block_degrees_out;
    float block_reduction_rate;
    // Computed info
    float overall_entropy;
    int num_blocks_to_merge;
};

#endif // CPPSBP_PARTITION_HPP
