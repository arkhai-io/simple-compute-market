/**
 * upgrade-local.ts — Upgrade all three ERC-8004 vanity proxies on local Anvil.
 *
 * Idempotent: checks each proxy's ERC-1967 implementation slot before acting;
 * skips any that are already upgraded.
 *
 * Uses anvil_impersonateAccount so no owner private key is needed.
 * Implementation addresses are computed fresh from compiled artifacts via CREATE2
 * — no stale presigned transactions involved.
 *
 * Run via:  npx hardhat run scripts/upgrade-local.ts --network anvil
 */

import hre from "hardhat";
import {
  createPublicClient,
  createWalletClient,
  http,
  keccak256,
  getCreate2Address,
  encodeFunctionData,
  type Hex,
} from "viem";
import { waitForTransactionReceipt } from "viem/actions";

const RPC_URL = process.env.RPC_URL || "http://anvil:8545";

// Owner hardcoded in MinimalUUPS.sol line 19 — controls all three proxies.
const OWNER = "0x547289319C3e6aedB179C0b8e8aF0B5ACd062603" as `0x${string}`;

// SAFE Singleton CREATE2 factory — same address on every chain.
const FACTORY = "0x914d7Fec6aaC8cd542e72Bca78B30650d45643d7" as `0x${string}`;

// ERC-1967 implementation storage slot.
const IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc" as `0x${string}`;

// Deterministic salts used by deploy-vanity.ts for implementation contracts.
const IMPL_SALTS: Record<string, Hex> = {
  identity:   "0x0000000000000000000000000000000000000000000000000000000000000005",
  reputation: "0x0000000000000000000000000000000000000000000000000000000000000006",
  validation: "0x0000000000000000000000000000000000000000000000000000000000000007",
};

// Vanity proxy addresses (same on all networks at chain 31337 testnet).
const PROXIES = {
  identity:   "0x8004A818BFB912233c491871b3d84c89A494BD9e" as `0x${string}`,
  reputation: "0x8004B663056A597Dffe9eCcC1965A193B7388713" as `0x${string}`,
  validation: "0x8004Cb1BF31DAf7788923b405b754f57acEB4272" as `0x${string}`,
};

async function main() {
  const transport = http(RPC_URL);
  const publicClient = createPublicClient({ transport });

  // ── 1. Load compiled artifacts + compute expected implementation addresses ──
  const idArt  = await hre.artifacts.readArtifact("IdentityRegistryUpgradeable");
  const repArt = await hre.artifacts.readArtifact("ReputationRegistryUpgradeable");
  const valArt = await hre.artifacts.readArtifact("ValidationRegistryUpgradeable");
  const minArt = await hre.artifacts.readArtifact("MinimalUUPS");

  const implAddr = (bytecode: string, salt: string): `0x${string}` =>
    getCreate2Address({
      from: FACTORY,
      salt: salt as `0x${string}`,
      bytecodeHash: keccak256(bytecode as `0x${string}`),
    });

  const idImpl  = implAddr(idArt.bytecode,  IMPL_SALTS.identity);
  const repImpl = implAddr(repArt.bytecode, IMPL_SALTS.reputation);
  const valImpl = implAddr(valArt.bytecode, IMPL_SALTS.validation);

  console.log("=".repeat(72));
  console.log("Upgrading ERC-8004 Vanity Proxies (Anvil Impersonation)");
  console.log("=".repeat(72));
  console.log(`RPC: ${RPC_URL}`);
  console.log(`Owner: ${OWNER}`);
  console.log("");
  console.log("Implementation addresses (computed from artifacts):");
  console.log(`  IdentityRegistry:   ${idImpl}`);
  console.log(`  ReputationRegistry: ${repImpl}`);
  console.log(`  ValidationRegistry: ${valImpl}`);
  console.log("");

  // ── 2. Determine which proxies need upgrading ──
  const upgrades = [
    {
      name: "IdentityRegistry",
      proxy: PROXIES.identity,
      impl: idImpl,
      initData: encodeFunctionData({
        abi: idArt.abi,
        functionName: "initialize",
        args: [],
      }),
    },
    {
      name: "ReputationRegistry",
      proxy: PROXIES.reputation,
      impl: repImpl,
      initData: encodeFunctionData({
        abi: repArt.abi,
        functionName: "initialize",
        args: [PROXIES.identity],
      }),
    },
    {
      name: "ValidationRegistry",
      proxy: PROXIES.validation,
      impl: valImpl,
      initData: encodeFunctionData({
        abi: valArt.abi,
        functionName: "initialize",
        args: [PROXIES.identity],
      }),
    },
  ];

  const toUpgrade: typeof upgrades = [];
  for (const u of upgrades) {
    const slot = await publicClient.getStorageAt({ address: u.proxy, slot: IMPL_SLOT });
    const current = ("0x" + (slot ?? "0x00").slice(-40)).toLowerCase();
    if (current === u.impl.toLowerCase()) {
      console.log(`${u.name}: ✅ already upgraded  (${current})`);
    } else {
      console.log(`${u.name}: needs upgrade  (current: ${current}  →  expected: ${u.impl})`);
      toUpgrade.push(u);
    }
  }

  if (toUpgrade.length === 0) {
    console.log("\nAll proxies already upgraded — nothing to do.");
    return;
  }

  console.log("");

  // ── 3. Impersonate owner + fund ──
  await publicClient.request({
    method: "anvil_impersonateAccount" as any,
    params: [OWNER],
  });
  await publicClient.request({
    method: "anvil_setBalance" as any,
    params: [OWNER, "0x56BC75E2D63100000"],  // 100 ETH
  });
  console.log(`Owner impersonated and funded (100 ETH).`);

  const walletClient = createWalletClient({ account: OWNER, transport });

  // ── 4. Upgrade each proxy ──
  for (const u of toUpgrade) {
    const calldata = encodeFunctionData({
      abi: minArt.abi,
      functionName: "upgradeToAndCall",
      args: [u.impl, u.initData],
    });

    console.log(`\nUpgrading ${u.name}...`);
    const hash = await walletClient.sendTransaction({
      to: u.proxy,
      data: calldata,
      chain: null,  // let viem discover chain id from the node
    });
    console.log(`  tx: ${hash}`);

    const receipt = await waitForTransactionReceipt(publicClient, { hash });
    if (receipt.status !== "success") {
      throw new Error(`${u.name} upgrade FAILED at block ${receipt.blockNumber}`);
    }
    console.log(`  ✅ block ${receipt.blockNumber}  gas ${receipt.gasUsed}`);
  }

  // ── 5. Stop impersonation + verify ──
  await publicClient.request({
    method: "anvil_stopImpersonatingAccount" as any,
    params: [OWNER],
  });

  console.log("\nVerifying...");
  for (const u of toUpgrade) {
    const slot = await publicClient.getStorageAt({ address: u.proxy, slot: IMPL_SLOT });
    const current = ("0x" + (slot ?? "0x00").slice(-40)).toLowerCase();
    if (current !== u.impl.toLowerCase()) {
      throw new Error(`${u.name} verification failed: impl slot = ${current}`);
    }
    console.log(`  ${u.name}: ✅ verified  (${current})`);
  }

  console.log("\n" + "=".repeat(72));
  console.log("All registry upgrades complete.");
  console.log("=".repeat(72));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
