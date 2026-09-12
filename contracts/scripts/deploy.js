const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [admin] = await hre.ethers.getSigners();
  console.log("Deploying RECRegistry with admin:", admin.address);

  const RECRegistry = await hre.ethers.getContractFactory("RECRegistry");
  const registry = await RECRegistry.deploy(admin.address);
  await registry.waitForDeployment();

  const address = await registry.getAddress();
  console.log("RECRegistry deployed to:", address);

  const artifact = await hre.artifacts.readArtifact("RECRegistry");

  const chainDir = path.join(__dirname, "..", "..", "backend", "chain");
  fs.mkdirSync(chainDir, { recursive: true });

  fs.writeFileSync(
    path.join(chainDir, "contract_abi.json"),
    JSON.stringify(artifact.abi, null, 2)
  );
  fs.writeFileSync(
    path.join(chainDir, "contract_address.json"),
    JSON.stringify({ address }, null, 2)
  );
  fs.writeFileSync(
    path.join(chainDir, "deployment_info.json"),
    JSON.stringify(
      {
        network: hre.network.name,
        address,
        admin: admin.address,
        deployedAt: new Date().toISOString(),
      },
      null,
      2
    )
  );

  console.log("Wrote ABI + address to backend/chain/");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
