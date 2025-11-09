// SPDX-License-Identifier: MIT
pragma solidity >= 0.5.28;

// type Id is bytes32;

struct MarketParams {
  address loanToken;
  address collateralToken;
  address oracle;
  address irm;
  uint256 lltv;
}

/// @dev Warning: For `feeRecipient`, `supplyShares` does not contain the accrued shares since the last interest
/// accrual.
struct Position {
  uint256 supplyShares;
  uint128 borrowShares;
  uint128 collateral;
}

/// @dev Warning: `totalSupplyAssets` does not contain the accrued interest since the last interest accrual.
/// @dev Warning: `totalBorrowAssets` does not contain the accrued interest since the last interest accrual.
/// @dev Warning: `totalSupplyShares` does not contain the additional shares accrued by `feeRecipient` since the last
/// interest accrual.
struct Market {
  uint128 totalSupplyAssets;
  uint128 totalSupplyShares;
  uint128 totalBorrowAssets;
  uint128 totalBorrowShares;
  uint128 lastUpdate;
  uint128 fee;
}

struct Authorization {
  address authorizer;
  address authorized;
  bool isAuthorized;
  uint256 nonce;
  uint256 deadline;
}

struct Signature {
  uint8 v;
  bytes32 r;
  bytes32 s;
}

/// @dev This interface is used for factorizing IMoolahStaticTyping and IMoolah.
/// @dev Consider using the IMoolah interface instead of this one.
interface IMoolahBase {

  /// @notice Executes a flash loan.
  /// @dev Flash loans have access to the whole balance of the contract (the liquidity and deposited collateral of all
  /// markets combined, plus donations).
  /// @dev Warning: Not ERC-3156 compliant but compatibility is easily reached:
  /// - `flashFee` is zero.
  /// - `maxFlashLoan` is the token's balance of this contract.
  /// - The receiver of `assets` is the caller.
  /// @param token The token to flash loan.
  /// @param assets The amount of assets to flash loan.
  /// @param data Arbitrary data to pass to the `onMoolahFlashLoan` callback.
  function flashLoan(address token, uint256 assets, bytes calldata data) external;

}


/// @title IMoolah
/// @author Lista DAO
/// @dev Use this interface for Moolah to have access to all the functions with the appropriate function signatures.
interface IMoolah is IMoolahBase {

  /// @notice grants `role` to `account`.
  function grantRole(bytes32 role, address account) external;
}
