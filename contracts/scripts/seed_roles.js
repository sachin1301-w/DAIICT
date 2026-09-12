const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

// Hardhat's local node always derives the same 20 accounts from its
// well-known deterministic mnemonic ("test test test ... junk") -- fine for
// a local dev chain, never use these keys anywhere else. Hardcoded here
// (rather than re-parsed from `npx hardhat node`'s console output every
// time) since they are constant across every restart.
const DEV_PRIVATE_KEYS = [
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
  "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
  "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
  "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
  "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
  "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
  "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e",
  "0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356",
  "0xdbda1821b80551c9d65939329250298aa3472ba22feea921c0cf5d620ea67b97",
  "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6",
];

const ROLE_ASSIGNMENTS = [
  { index: 1, role: "ISSUER_ROLE", label: "Issuer" },
  { index: 2, role: "GENERATOR_ROLE", label: "Generator: Plant A (Solar)" },
  { index: 3, role: "GENERATOR_ROLE", label: "Generator: Sunrise Wind Farm" },
  { index: 4, role: "TRADER_ROLE", label: "Trader: Broker X" },
  { index: 5, role: "TRADER_ROLE", label: "Trader: Broker Y" },
  { index: 6, role: "TRADER_ROLE", label: "Trader: Company B" },
  { index: 7, role: "TRADER_ROLE", label: "Trader: Company C" },
  { index: 8, role: "REGULATOR_ROLE", label: "Regulator" },
  { index: 9, role: "AUDITOR_ROLE", label: "Auditor" },
];

async function main() {
  const addressPath = path.join(__dirname, "..", "..", "backend", "chain", "contract_address.json");
  const { address } = JSON.parse(fs.readFileSync(addressPath, "utf8"));

  const RECRegistry = await hre.ethers.getContractFactory("RECRegistry");
  const registry = RECRegistry.attach(address);

  const signers = await hre.ethers.getSigners();
  const admin = signers[0];

  const wallets = [{
    index: 0, role: "ADMIN/REGULATOR", label: "Admin",
    address: admin.address, private_key: DEV_PRIVATE_KEYS[0],
  }];

  for (const { index, role, label } of ROLE_ASSIGNMENTS) {
    const signer = signers[index];
    const roleHash = await registry[role]();
    const tx = await registry.connect(admin).grantRole(roleHash, signer.address);
    await tx.wait();
    console.log(`Granted ${role} to account #${index} (${signer.address}) -- ${label}`);
    wallets.push({ index, role, label, address: signer.address, private_key: DEV_PRIVATE_KEYS[index] });
  }

  const walletsPath = path.join(__dirname, "..", "..", "backend", "chain", "wallets.json");
  fs.writeFileSync(walletsPath, JSON.stringify(wallets, null, 2));
  console.log("Wrote persona wallet list to backend/chain/wallets.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
