// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test, console2} from "forge-std/Test.sol";
import {GavelEscrow} from "../src/GavelEscrow.sol";

/// @title GavelEscrowTest
/// @notice Unit tests for the Gavel escrow lifecycle:
///         open -> join -> rule -> funds released.
contract GavelEscrowTest is Test {
    GavelEscrow public escrow;

    address public arbiter = makeAddr("arbiter");
    address public claimant = makeAddr("claimant");
    address public respondent = makeAddr("respondent");
    address public stranger = makeAddr("stranger");

    bytes32 public constant DISPUTE_ID = keccak256("dispute-1");
    uint256 public constant DEPOSIT = 1 ether;

    function setUp() public {
        escrow = new GavelEscrow(arbiter);
        vm.deal(claimant, 10 ether);
        vm.deal(respondent, 10 ether);
        vm.deal(stranger, 10 ether);
    }

    /*//////////////////////////////////////////////////////////////
                                   OPEN
    //////////////////////////////////////////////////////////////*/

    /// @notice openDispute creates the dispute and locks the funds.
    function test_openDispute_createsAndLocksFunds() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);

        GavelEscrow.Dispute memory d = escrow.getDispute(DISPUTE_ID);
        assertEq(d.claimant, claimant);
        assertEq(d.respondent, respondent);
        assertEq(d.amount, DEPOSIT);
        assertEq(d.state, 1); // open
        assertEq(d.winner, address(0));
        assertEq(address(escrow).balance, DEPOSIT);
    }

    /// @notice Emits DisputeOpened with the right fields.
    function test_openDispute_emitsEvent() public {
        vm.expectEmit(true, false, false, true);
        emit GavelEscrow.DisputeOpened(DISPUTE_ID, claimant, respondent, DEPOSIT);

        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
    }

    function test_openDispute_revertsOnZeroDeposit() public {
        vm.prank(claimant);
        vm.expectRevert(GavelEscrow.ZeroDeposit.selector);
        escrow.openDispute(DISPUTE_ID, respondent);
    }

    function test_openDispute_revertsOnZeroRespondent() public {
        vm.prank(claimant);
        vm.expectRevert(GavelEscrow.ZeroRespondent.selector);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, address(0));
    }

    function test_openDispute_revertsOnSelfDispute() public {
        vm.prank(claimant);
        vm.expectRevert(GavelEscrow.SelfDispute.selector);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, claimant);
    }

    function test_openDispute_revertsOnDuplicateId() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);

        vm.prank(claimant);
        vm.expectRevert(GavelEscrow.DisputeExists.selector);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
    }

    function test_constructor_revertsOnZeroArbiter() public {
        vm.expectRevert(GavelEscrow.ZeroArbiter.selector);
        new GavelEscrow(address(0));
    }

    /*//////////////////////////////////////////////////////////////
                                   JOIN
    //////////////////////////////////////////////////////////////*/

    /// @notice A matching deposit from the respondent joins the dispute.
    function test_joinDispute_matchesAndJoins() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);

        vm.expectEmit(true, false, false, true);
        emit GavelEscrow.DisputeJoined(DISPUTE_ID, DEPOSIT * 2);

        vm.prank(respondent);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        GavelEscrow.Dispute memory d = escrow.getDispute(DISPUTE_ID);
        assertEq(d.state, 2); // joined
        assertEq(address(escrow).balance, DEPOSIT * 2);
    }

    /// @notice joinDispute with a wrong amount reverts.
    function test_joinDispute_wrongAmountReverts() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);

        vm.prank(respondent);
        vm.expectRevert(GavelEscrow.WrongAmount.selector);
        escrow.joinDispute{value: DEPOSIT - 1}(DISPUTE_ID);

        vm.prank(respondent);
        vm.expectRevert(GavelEscrow.WrongAmount.selector);
        escrow.joinDispute{value: DEPOSIT + 1}(DISPUTE_ID);
    }

    /// @notice joinDispute by anyone other than the respondent reverts.
    function test_joinDispute_nonRespondentReverts() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);

        vm.prank(stranger);
        vm.expectRevert(GavelEscrow.NotRespondent.selector);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        vm.prank(claimant);
        vm.expectRevert(GavelEscrow.NotRespondent.selector);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);
    }

    function test_joinDispute_unknownDisputeReverts() public {
        vm.prank(respondent);
        vm.expectRevert(GavelEscrow.DisputeNotFound.selector);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);
    }

    /*//////////////////////////////////////////////////////////////
                                   RULE
    //////////////////////////////////////////////////////////////*/

    /// @notice submitRuling pays the FULL pot to the winner and emits events.
    function test_submitRuling_paysFullPotToWinner() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
        vm.prank(respondent);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        bytes32 transcriptHash = keccak256("transcript");
        uint256 winnerBefore = respondent.balance;

        vm.expectEmit(true, false, false, true);
        emit GavelEscrow.RulingSubmitted(DISPUTE_ID, respondent, transcriptHash);
        vm.expectEmit(true, false, false, true);
        emit GavelEscrow.FundsReleased(DISPUTE_ID, respondent, DEPOSIT * 2);

        vm.prank(arbiter);
        escrow.submitRuling(DISPUTE_ID, respondent, transcriptHash);

        assertEq(respondent.balance, winnerBefore + DEPOSIT * 2);
        assertEq(address(escrow).balance, 0);

        GavelEscrow.Dispute memory d = escrow.getDispute(DISPUTE_ID);
        assertEq(d.state, 3); // ruled
        assertEq(d.winner, respondent);
        assertEq(d.transcriptHash, transcriptHash);
    }

    /// @notice The claimant can win too — full pot, no fee skimmed.
    function test_submitRuling_paysClaimantWhenTheyWin() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
        vm.prank(respondent);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        uint256 claimantBefore = claimant.balance;

        vm.prank(arbiter);
        escrow.submitRuling(DISPUTE_ID, claimant, keccak256("t"));

        assertEq(claimant.balance, claimantBefore + DEPOSIT * 2);
    }

    /// @notice submitRuling by anyone other than the arbiter reverts.
    function test_submitRuling_nonArbiterReverts() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
        vm.prank(respondent);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        vm.prank(claimant);
        vm.expectRevert(GavelEscrow.NotArbiter.selector);
        escrow.submitRuling(DISPUTE_ID, claimant, keccak256("t"));

        vm.prank(stranger);
        vm.expectRevert(GavelEscrow.NotArbiter.selector);
        escrow.submitRuling(DISPUTE_ID, respondent, keccak256("t"));
    }

    /// @notice Ruling the same dispute twice reverts.
    function test_submitRuling_twiceReverts() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
        vm.prank(respondent);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        vm.prank(arbiter);
        escrow.submitRuling(DISPUTE_ID, claimant, keccak256("t"));

        vm.prank(arbiter);
        vm.expectRevert(GavelEscrow.AlreadyRuled.selector);
        escrow.submitRuling(DISPUTE_ID, respondent, keccak256("t"));
    }

    /// @notice Ruling before the respondent has joined reverts.
    function test_submitRuling_unjoinedDisputeReverts() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);

        vm.prank(arbiter);
        vm.expectRevert(GavelEscrow.NotReady.selector);
        escrow.submitRuling(DISPUTE_ID, claimant, keccak256("t"));
    }

    function test_submitRuling_unknownDisputeReverts() public {
        vm.prank(arbiter);
        vm.expectRevert(GavelEscrow.NotReady.selector);
        escrow.submitRuling(DISPUTE_ID, claimant, keccak256("t"));
    }

    /// @notice The winner must be one of the two parties.
    function test_submitRuling_invalidWinnerReverts() public {
        vm.prank(claimant);
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
        vm.prank(respondent);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        vm.prank(arbiter);
        vm.expectRevert(GavelEscrow.InvalidWinner.selector);
        escrow.submitRuling(DISPUTE_ID, stranger, keccak256("t"));

        vm.prank(arbiter);
        vm.expectRevert(GavelEscrow.InvalidWinner.selector);
        escrow.submitRuling(DISPUTE_ID, address(0), keccak256("t"));
    }

    /*//////////////////////////////////////////////////////////////
                          REENTRANCY GUARD
    //////////////////////////////////////////////////////////////*/

    /// @notice A malicious winner contract cannot reenter submitRuling.
    function test_submitRuling_reentrantWinnerBlocked() public {
        ReentrantWinner attacker = new ReentrantWinner(address(escrow));

        vm.deal(address(attacker), 10 ether);
        vm.prank(address(attacker));
        escrow.openDispute{value: DEPOSIT}(DISPUTE_ID, respondent);
        vm.prank(respondent);
        escrow.joinDispute{value: DEPOSIT}(DISPUTE_ID);

        attacker.arm(DISPUTE_ID, address(attacker), keccak256("evil"));

        vm.prank(arbiter);
        escrow.submitRuling(DISPUTE_ID, address(attacker), keccak256("t"));

        // The payout still succeeded exactly once despite the reentry attempt.
        // Attacker is also the claimant: 10 ETH funded, 1 paid as deposit,
        // 2 returned as winner => 11 ETH. A successful reentry would have
        // drained the contract and reverted on second rule (AlreadyRuled).
        assertEq(address(attacker).balance, 11 ether);
        assertEq(address(escrow).balance, 0);
    }
}

/// @notice A winner contract that tries to reenter submitRuling on receive().
contract ReentrantWinner {
    GavelEscrow public immutable escrow;
    bytes32 public disputeId;
    address public winner;
    bytes32 public transcriptHash;
    bool public armed;

    constructor(address escrow_) {
        escrow = GavelEscrow(payable(escrow_));
    }

    function arm(bytes32 d, address w, bytes32 t) external {
        disputeId = d;
        winner = w;
        transcriptHash = t;
        armed = true;
    }

    function openDispute(bytes32 id, address respondent) external payable {
        escrow.openDispute{value: msg.value}(id, respondent);
    }

    receive() external payable {
        if (armed) {
            armed = false; // attempt reentry only once
            try escrow.submitRuling(disputeId, winner, transcriptHash) {} catch {}
        }
    }
}
