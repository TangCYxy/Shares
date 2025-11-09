// SPDX-License-Identifier: MIT
pragma solidity > 0.5.28;

/// @title IMoolahLiquidateCallback
/// @notice Interface that liquidators willing to use `liquidate`'s callback must implement.
interface IMoolahLiquidateCallback {
  /// @notice Callback called when a liquidation occurs.
  /// @dev The callback is called only if data is not empty.
  /// @param repaidAssets The amount of repaid assets.
  /// @param data Arbitrary data passed to the `liquidate` function.
  function onMoolahLiquidate(uint256 repaidAssets, bytes calldata data) external;
}

/// @title IMoolahRepayCallback
/// @notice Interface that users willing to use `repay`'s callback must implement.
interface IMoolahRepayCallback {
  /// @notice Callback called when a repayment occurs.
  /// @dev The callback is called only if data is not empty.
  /// @param assets The amount of repaid assets.
  /// @param data Arbitrary data passed to the `repay` function.
  function onMoolahRepay(uint256 assets, bytes calldata data) external;
}

/// @title IMoolahSupplyCallback
/// @notice Interface that users willing to use `supply`'s callback must implement.
interface IMoolahSupplyCallback {
  /// @notice Callback called when a supply occurs.
  /// @dev The callback is called only if data is not empty.
  /// @param assets The amount of supplied assets.
  /// @param data Arbitrary data passed to the `supply` function.
  function onMoolahSupply(uint256 assets, bytes calldata data) external;
}

/// @title IMoolahSupplyCollateralCallback
/// @notice Interface that users willing to use `supplyCollateral`'s callback must implement.
interface IMoolahSupplyCollateralCallback {
  /// @notice Callback called when a supply of collateral occurs.
  /// @dev The callback is called only if data is not empty.
  /// @param assets The amount of supplied collateral.
  /// @param data Arbitrary data passed to the `supplyCollateral` function.
  function onMoolahSupplyCollateral(uint256 assets, bytes calldata data) external;
}

/// @title IMoolahFlashLoanCallback
/// @notice Interface that users willing to use `flashLoan`'s callback must implement.
interface IMoolahFlashLoanCallback {
  /// @notice Callback called when a flash loan occurs.
  /// @dev The callback is called only if data is not empty.
  /// @param assets The amount of assets that was flash loaned.
  /// @param data Arbitrary data passed to the `flashLoan` function.
  function onMoolahFlashLoan(uint256 assets, bytes calldata data) external;
}
