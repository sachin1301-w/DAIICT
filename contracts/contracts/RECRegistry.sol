// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";

/// @title RECRegistry
/// @notice On-chain lifecycle registry for Renewable Energy Certificates (RECs).
/// Raw generation data stays off-chain (SQLite); only a SHA-256 hash of it is
/// anchored here, so any later tampering with the off-chain record can be
/// detected by recomputing the hash and comparing it against this contract.
contract RECRegistry is AccessControl {
    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE");
    bytes32 public constant GENERATOR_ROLE = keccak256("GENERATOR_ROLE");
    bytes32 public constant TRADER_ROLE = keccak256("TRADER_ROLE");
    bytes32 public constant REGULATOR_ROLE = keccak256("REGULATOR_ROLE");
    bytes32 public constant AUDITOR_ROLE = keccak256("AUDITOR_ROLE");

    enum Status { ACTIVE, RETIRED, REVOKED, FROZEN }

    struct REC {
        string recId;
        string generatorId;
        uint256 quantity;
        uint256 issueTimestamp;
        address currentOwner;
        Status status;
        bytes32 generationDataHash;
        bool exists;
    }

    mapping(string => REC) private recs;
    string[] private recIds;

    event RECIssued(string recId, string generatorId, uint256 quantity, address owner, bytes32 dataHash);
    event RECTransferred(string recId, address indexed from, address indexed to, uint256 quantity);
    event RECRetired(string recId, address indexed by);
    event RECRevoked(string recId, address indexed by, string reason);
    event RECFrozen(string recId, address indexed by);
    event RECUnfrozen(string recId, address indexed by);

    constructor(address admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(REGULATOR_ROLE, admin);
        _grantRole(ISSUER_ROLE, admin);
    }

    // ---------------- lifecycle ----------------

    function issueREC(
        string calldata recId,
        string calldata generatorId,
        uint256 quantity,
        address owner,
        bytes32 generationDataHash
    ) external onlyRole(ISSUER_ROLE) {
        require(!recs[recId].exists, "REC already exists");
        require(quantity > 0, "quantity must be > 0");
        require(owner != address(0), "invalid owner");

        recs[recId] = REC({
            recId: recId,
            generatorId: generatorId,
            quantity: quantity,
            issueTimestamp: block.timestamp,
            currentOwner: owner,
            status: Status.ACTIVE,
            generationDataHash: generationDataHash,
            exists: true
        });
        recIds.push(recId);
        emit RECIssued(recId, generatorId, quantity, owner, generationDataHash);
    }

    function transferREC(string calldata recId, address to) external {
        REC storage rec = _mustExist(recId);
        require(rec.status == Status.ACTIVE, "REC not active");
        require(msg.sender == rec.currentOwner, "caller is not current owner");
        require(to != address(0), "invalid recipient");

        address from = rec.currentOwner;
        rec.currentOwner = to;
        emit RECTransferred(recId, from, to, rec.quantity);
    }

    function retireREC(string calldata recId) external {
        REC storage rec = _mustExist(recId);
        require(rec.status == Status.ACTIVE, "REC not active");
        require(msg.sender == rec.currentOwner, "caller is not current owner");

        rec.status = Status.RETIRED;
        emit RECRetired(recId, msg.sender);
    }

    function revokeREC(string calldata recId, string calldata reason) external onlyRole(REGULATOR_ROLE) {
        REC storage rec = _mustExist(recId);
        require(rec.status != Status.REVOKED, "already revoked");

        rec.status = Status.REVOKED;
        emit RECRevoked(recId, msg.sender, reason);
    }

    function freezeREC(string calldata recId) external onlyRole(REGULATOR_ROLE) {
        REC storage rec = _mustExist(recId);
        require(rec.status == Status.ACTIVE, "can only freeze an active REC");

        rec.status = Status.FROZEN;
        emit RECFrozen(recId, msg.sender);
    }

    function unfreezeREC(string calldata recId) external onlyRole(REGULATOR_ROLE) {
        REC storage rec = _mustExist(recId);
        require(rec.status == Status.FROZEN, "REC is not frozen");

        rec.status = Status.ACTIVE;
        emit RECUnfrozen(recId, msg.sender);
    }

    // ---------------- views ----------------

    function verifyREC(string calldata recId) external view returns (
        string memory generatorId,
        uint256 quantity,
        uint256 issueTimestamp,
        address currentOwner,
        Status status,
        bytes32 generationDataHash
    ) {
        REC storage rec = _mustExist(recId);
        return (
            rec.generatorId, rec.quantity, rec.issueTimestamp,
            rec.currentOwner, rec.status, rec.generationDataHash
        );
    }

    function totalRECs() external view returns (uint256) {
        return recIds.length;
    }

    function recIdAt(uint256 index) external view returns (string memory) {
        return recIds[index];
    }

    // ---------------- internal ----------------

    function _mustExist(string calldata recId) internal view returns (REC storage) {
        REC storage rec = recs[recId];
        require(rec.exists, "REC does not exist");
        return rec;
    }
}
