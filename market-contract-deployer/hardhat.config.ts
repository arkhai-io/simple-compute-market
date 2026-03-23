// Minimal Hardhat config for local Anvil deployment.
// This replaces the official erc-8004-contracts hardhat.config.ts inside the
// market-contract-deployer image so that the deploy scripts connect to Anvil
// (via RPC_URL env var) rather than expecting a localhost:8545 node.
import "@nomicfoundation/hardhat-ethers";
import hardhatToolboxViemPlugin from "@nomicfoundation/hardhat-toolbox-viem";
import type { HardhatUserConfig } from "hardhat/config";

const config: HardhatUserConfig = {
  defaultNetwork: "anvil",
  plugins: [hardhatToolboxViemPlugin],
  solidity: {
    profiles: {
      default: {
        version: "0.8.24",
        settings: {
          evmVersion: "shanghai",
          optimizer: { enabled: true, runs: 200 },
          viaIR: true,
        },
      },
    },
  },
  networks: {
    anvil: {
      type: "http",
      chainType: "l1",
      url: process.env.RPC_URL || "http://anvil:8545",
    },
    // deploy-create2-factory.ts hardcodes hre.network.connect("localhost") — map
    // it to the same Anvil endpoint so both scripts hit the same node.
    localhost: {
      type: "http",
      chainType: "l1",
      url: process.env.RPC_URL || "http://anvil:8545",
    },
  },
};

export default config;
