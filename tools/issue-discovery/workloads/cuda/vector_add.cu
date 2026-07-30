#include <cuda_runtime.h>

#include <cstdio>
#include <cstdlib>
#include <vector>

namespace {

constexpr int kElements = 1024;
constexpr long long kExpectedChecksum =
    3LL * kElements * (kElements - 1) / 2;

void check_cuda(cudaError_t status, const char* operation) {
  if (status == cudaSuccess) {
    return;
  }
  std::fprintf(
      stderr,
      "SCM_CUDA_VECTOR_ADD_ERROR operation=%s code=%d\n",
      operation,
      static_cast<int>(status));
  std::exit(1);
}

__global__ void vector_add(const int* left, const int* right, int* result) {
  const int index = blockIdx.x * blockDim.x + threadIdx.x;
  if (index < kElements) {
    result[index] = left[index] + right[index];
  }
}

}  // namespace

int main() {
  int visible_devices = 0;
  check_cuda(cudaGetDeviceCount(&visible_devices), "device-count");
  if (visible_devices != 1) {
    std::fprintf(
        stderr,
        "SCM_CUDA_VECTOR_ADD_ERROR expected_visible_devices=1 actual=%d\n",
        visible_devices);
    return 1;
  }

  std::vector<int> left(kElements);
  std::vector<int> right(kElements);
  std::vector<int> result(kElements);
  for (int index = 0; index < kElements; ++index) {
    left[index] = index;
    right[index] = 2 * index;
  }

  int* device_left = nullptr;
  int* device_right = nullptr;
  int* device_result = nullptr;
  const std::size_t bytes = kElements * sizeof(int);
  check_cuda(
      cudaMalloc(reinterpret_cast<void**>(&device_left), bytes),
      "malloc-left");
  check_cuda(
      cudaMalloc(reinterpret_cast<void**>(&device_right), bytes),
      "malloc-right");
  check_cuda(
      cudaMalloc(reinterpret_cast<void**>(&device_result), bytes),
      "malloc-result");
  check_cuda(
      cudaMemcpy(device_left, left.data(), bytes, cudaMemcpyHostToDevice),
      "copy-left");
  check_cuda(
      cudaMemcpy(device_right, right.data(), bytes, cudaMemcpyHostToDevice),
      "copy-right");

  constexpr int kThreads = 256;
  constexpr int kBlocks = (kElements + kThreads - 1) / kThreads;
  vector_add<<<kBlocks, kThreads>>>(device_left, device_right, device_result);
  check_cuda(cudaGetLastError(), "launch");
  check_cuda(cudaDeviceSynchronize(), "synchronize");
  check_cuda(
      cudaMemcpy(result.data(), device_result, bytes, cudaMemcpyDeviceToHost),
      "copy-result");

  check_cuda(cudaFree(device_result), "free-result");
  check_cuda(cudaFree(device_right), "free-right");
  check_cuda(cudaFree(device_left), "free-left");

  long long checksum = 0;
  for (int index = 0; index < kElements; ++index) {
    const int expected = 3 * index;
    if (result[index] != expected) {
      std::fprintf(
          stderr,
          "SCM_CUDA_VECTOR_ADD_ERROR index=%d expected=%d actual=%d\n",
          index,
          expected,
          result[index]);
      return 1;
    }
    checksum += result[index];
  }
  if (checksum != kExpectedChecksum) {
    std::fprintf(
        stderr,
        "SCM_CUDA_VECTOR_ADD_ERROR expected_checksum=%lld actual_checksum=%lld\n",
        kExpectedChecksum,
        checksum);
    return 1;
  }

  std::printf(
      "SCM_CUDA_VECTOR_ADD_OK elements=%d checksum=%lld\n",
      kElements,
      checksum);
  return 0;
}
