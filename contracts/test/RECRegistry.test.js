const { expect } = require("chai");
const { ethers } = require("hardhat");
const { keccak256, toUtf8Bytes } = ethers;

describe("RECRegistry", function () {
  let registry, admin, issuer, plantOwner, buyer, regulator, stranger;

  beforeEach(async function () {
    [admin, issuer, plantOwner, buyer, regulator, stranger] = await ethers.getSigners();

    const RECRegistry = await ethers.getContractFactory("RECRegistry");
    registry = await RECRegistry.deploy(admin.address);
    await registry.waitForDeployment();

    const ISSUER_ROLE = await registry.ISSUER_ROLE();
    const REGULATOR_ROLE = await registry.REGULATOR_ROLE();
    await registry.connect(admin).grantRole(ISSUER_ROLE, issuer.address);
    await registry.connect(admin).grantRole(REGULATOR_ROLE, regulator.address);
  });

  function hash(data) {
    return keccak256(toUtf8Bytes(data));
  }

  it("issues a REC only via ISSUER_ROLE", async function () {
    await expect(
      registry.connect(stranger).issueREC("REC-1", "GEN-1", 100, plantOwner.address, hash("data"))
    ).to.be.reverted;

    await expect(
      registry.connect(issuer).issueREC("REC-1", "GEN-1", 100, plantOwner.address, hash("data"))
    ).to.emit(registry, "RECIssued");

    const rec = await registry.verifyREC("REC-1");
    expect(rec.currentOwner).to.equal(plantOwner.address);
    expect(rec.status).to.equal(0); // ACTIVE
  });

  it("rejects duplicate REC ids", async function () {
    await registry.connect(issuer).issueREC("REC-DUP", "GEN-1", 100, plantOwner.address, hash("a"));
    await expect(
      registry.connect(issuer).issueREC("REC-DUP", "GEN-1", 100, plantOwner.address, hash("b"))
    ).to.be.revertedWith("REC already exists");
  });

  it("only current owner can transfer, and only while ACTIVE", async function () {
    await registry.connect(issuer).issueREC("REC-2", "GEN-1", 100, plantOwner.address, hash("data"));

    await expect(registry.connect(stranger).transferREC("REC-2", buyer.address))
      .to.be.revertedWith("caller is not current owner");

    await expect(registry.connect(plantOwner).transferREC("REC-2", buyer.address))
      .to.emit(registry, "RECTransferred");

    const rec = await registry.verifyREC("REC-2");
    expect(rec.currentOwner).to.equal(buyer.address);
  });

  it("prevents transferring a retired REC", async function () {
    await registry.connect(issuer).issueREC("REC-3", "GEN-1", 100, plantOwner.address, hash("data"));
    await registry.connect(plantOwner).retireREC("REC-3");

    await expect(
      registry.connect(plantOwner).transferREC("REC-3", buyer.address)
    ).to.be.revertedWith("REC not active");
  });

  it("only REGULATOR_ROLE can revoke, freeze or unfreeze", async function () {
    await registry.connect(issuer).issueREC("REC-4", "GEN-1", 100, plantOwner.address, hash("data"));

    await expect(registry.connect(stranger).revokeREC("REC-4", "fraud")).to.be.reverted;
    await expect(registry.connect(regulator).freezeREC("REC-4")).to.emit(registry, "RECFrozen");

    await expect(
      registry.connect(plantOwner).transferREC("REC-4", buyer.address)
    ).to.be.revertedWith("REC not active");

    await expect(registry.connect(regulator).unfreezeREC("REC-4")).to.emit(registry, "RECUnfrozen");
    await expect(registry.connect(regulator).revokeREC("REC-4", "confirmed fraud")).to.emit(registry, "RECRevoked");
  });

  it("verifyREC reverts for an unknown REC id", async function () {
    await expect(registry.verifyREC("NOPE")).to.be.revertedWith("REC does not exist");
  });
});
