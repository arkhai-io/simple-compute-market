import { defineChain } from "viem";

/**
 * Custom chain definitions for chains not yet in viem's built-in list.
 * Key must match the network name passed via --network to deploy-vanity.ts.
 *
 * The "anvil" entry is added here (not in the upstream repo) so that
 * `deploy-vanity.ts --network anvil` uses a direct viem HTTP connection
 * to the local Anvil node, bypassing Hardhat's in-process EVM.
 */
export const customChains: Record<string, ReturnType<typeof defineChain>> = {
  anvil: defineChain({
    id: 31337,
    name: "Anvil",
    nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
    rpcUrls: {
      default: { http: [process.env.RPC_URL || "http://anvil:8545"] },
    },
  }),
  xlayerTestnet: defineChain({
    id: 1952,
    name: "XLayer Testnet",
    nativeCurrency: { name: "OKB", symbol: "OKB", decimals: 18 },
    rpcUrls: { default: { http: ["https://testrpc.xlayer.tech"] } },
  }),
  goatTestnet: defineChain({
    id: 48816,
    name: "GOAT Testnet3",
    nativeCurrency: { name: "Bitcoin", symbol: "BTC", decimals: 18 },
    rpcUrls: { default: { http: ["https://rpc.testnet3.goat.network"] } },
  }),
  skaleBaseSepolia: defineChain({
    id: 324705682,
    name: "SKALE Base Sepolia",
    nativeCurrency: { name: "Credits", symbol: "CREDIT", decimals: 18 },
    rpcUrls: { default: { http: ["https://base-sepolia-testnet.skalenodes.com/v1/jubilant-horrible-ancha"] } },
  }),
  skaleBase: defineChain({
    id: 1187947933,
    name: "SKALE Base",
    nativeCurrency: { name: "Credits", symbol: "CREDIT", decimals: 18 },
    rpcUrls: { default: { http: ["https://skale-base.skalenodes.com/v1/base"] } },
  }),
  arcTestnet: defineChain({
    id: 5042002,
    name: "Arc Testnet",
    nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
    rpcUrls: { default: { http: ["https://rpc.testnet.arc.network"] } },
  }),
};
