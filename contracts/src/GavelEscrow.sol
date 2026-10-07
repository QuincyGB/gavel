// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title GavelEscrow
/// @notice Escrow vault for Gavel, an AI small-claims court.
/// @dev Lifecycle: a claimant opens a dispute by locking a deposit; the
///      respondent joins by matching it; a trusted off-chain arbiter
///      (the Gavel backend) then submits a ruling, which releases the full
///      pot (both deposits) to the winner. The arbiter's identity is the
///      only trust assumption — funds cannot move otherwise.
///
///      Dispute states: 0 = none (disputeId unused), 1 = open, 2 = joined,
///      3 = ruled (terminal; funds already released).
///
///      The off-chain ruling transcript is hashed and stored on-chain
///      (`transcriptHash`) so anyone can later verify that the published
///      transcript matches the ruling the arbiter committed to.
contract GavelEscrow {
    /*//////////////////////////////////////////////////////////////
                                STRUCTS
    //////////////////////////////////////////////////////////////*/

    /// @notice A single escrowed dispute.
    struct Dispute {
        address claimant;       // party that opened the dispute
        address respondent;     // counterparty, set at open time
        uint256 amount;         // claimant's deposit (respondent must match exactly)
        uint8   state;          // 0=none, 1=open, 2=joined, 3=ruled
        address winner;         // set at ruling time
        bytes32 transcriptHash; // keccak256 of the public ruling transcript
    }

    /*//////////////////////////////////////////////////////////////
                                ERRORS
    //////////////////////////////////////////////////////////////*/

    error ZeroArbiter();
    error ZeroRespondent();
    error SelfDispute();
    error ZeroDeposit();
    error DisputeExists();
    error DisputeNotFound();
    error NotRespondent();
    error WrongAmount();
    error NotArbiter();
    error NotReady();
    error AlreadyRuled();
    error InvalidWinner();
    error TransferFailed();

    /*//////////////////////////////////////////////////////////////
                                EVENTS
    //////////////////////////////////////////////////////////////*/

    event DisputeOpened(
        bytes32 indexed disputeId,
        address claimant,
        address respondent,
        uint256 amount
    );
    event DisputeJoined(bytes32 indexed disputeId, uint256 totalAmount);
    event RulingSubmitted(
        bytes32 indexed disputeId,
        address winner,
        bytes32 transcriptHash
    );
    event FundsReleased(
        bytes32 indexed disputeId,
        address winner,
        uint256 amount
    );

    /*//////////////////////////////////////////////////////////////
                            STATE VARIABLES
    //////////////////////////////////////////////////////////////*/

    /// @notice The single address authorized to submit rulings.
    address public immutable arbiter;

    /// @notice disputeId => Dispute. state == 0 means the id is unused.
    mapping(bytes32 => Dispute) public disputes;

    /// @notice Minimal reentrancy lock (nonReentrant equivalent).
    bool private _locked;

    /*//////////////////////////////////////////////////////////////
                              CONSTRUCTOR
    //////////////////////////////////////////////////////////////*/

    /// @param arbiter_ The address allowed to call submitRuling.
    constructor(address arbiter_) {
        if (arbiter_ == address(0)) revert ZeroArbiter();
        arbiter = arbiter_;
    }

    /*//////////////////////////////////////////////////////////////
                           DISPUTE LIFECYCLE
    //////////////////////////////////////////////////////////////*/

    /// @notice Open a dispute and lock the claimant's deposit.
    /// @param disputeId Caller-chosen unique id for this dispute.
    /// @param respondent The counterparty; must not be zero or the caller.
    function openDispute(bytes32 disputeId, address respondent)
        external
        payable
    {
        if (disputes[disputeId].state != 0) revert DisputeExists();
        if (respondent == address(0)) revert ZeroRespondent();
        if (respondent == msg.sender) revert SelfDispute();
        if (msg.value == 0) revert ZeroDeposit();

        disputes[disputeId] = Dispute({
            claimant: msg.sender,
            respondent: respondent,
            amount: msg.value,
            state: 1, // open
            winner: address(0),
            transcriptHash: bytes32(0)
        });

        emit DisputeOpened(disputeId, msg.sender, respondent, msg.value);
    }

    /// @notice Respondent joins by matching the claimant's deposit exactly.
    /// @param disputeId The dispute to join.
    function joinDispute(bytes32 disputeId) external payable {
        Dispute storage d = disputes[disputeId];
        if (d.state != 1) revert DisputeNotFound(); // unused or already past open
        if (msg.sender != d.respondent) revert NotRespondent();
        if (msg.value != d.amount) revert WrongAmount();

        d.state = 2; // joined

        emit DisputeJoined(disputeId, d.amount * 2);
    }

    /// @notice Arbiter submits the ruling; the full pot goes to the winner.
    /// @dev Guarded against reentrancy; follows checks-effects-interactions.
    /// @param disputeId The dispute being ruled on.
    /// @param winner Must be the claimant or the respondent.
    /// @param transcriptHash keccak256 of the public ruling transcript.
    function submitRuling(
        bytes32 disputeId,
        address winner,
        bytes32 transcriptHash
    ) external {
        if (_locked) revert TransferFailed(); // reentrancy guard engaged
        _locked = true;

        Dispute storage d = disputes[disputeId];
        if (d.state == 3) {
            _locked = false;
            revert AlreadyRuled();
        }
        if (d.state != 2) {
            _locked = false;
            revert NotReady();
        }
        if (msg.sender != arbiter) {
            _locked = false;
            revert NotArbiter();
        }
        if (winner != d.claimant && winner != d.respondent) {
            _locked = false;
            revert InvalidWinner();
        }

        // Effects: mark ruled before any external interaction.
        d.state = 3;
        d.winner = winner;
        d.transcriptHash = transcriptHash;

        uint256 pot = d.amount * 2;

        emit RulingSubmitted(disputeId, winner, transcriptHash);
        emit FundsReleased(disputeId, winner, pot);

        // Interactions: release the full pot to the winner.
        (bool ok, ) = winner.call{value: pot}("");
        if (!ok) {
            _locked = false;
            revert TransferFailed();
        }

        _locked = false;
    }

    /*//////////////////////////////////////////////////////////////
                                 VIEWS
    //////////////////////////////////////////////////////////////*/

    /// @notice Return the full dispute record for an id.
    function getDispute(bytes32 disputeId)
        external
        view
        returns (Dispute memory)
    {
        return disputes[disputeId];
    }
}
