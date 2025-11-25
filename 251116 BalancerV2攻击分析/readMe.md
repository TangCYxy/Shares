
---
# 攻击总览
- **事件时间**：2025 年11月初
- **受影响服务**：BalancerV2 及其多链部署，其他fork项目等
- **损失规模**：1亿⬆️美金
- **直接影响原因**:
  * 机制上允许用户没有任何资产发起Swap操作（实际扣款操作在最后）
  * 通过swap操作触发rounding精度丢失漏洞（roundDown 和 roundUp）  
  * 通过BatchSwap的多次操作统一结算的机制放大了精度丢失问题带来的影响
  * 
- **攻击交易**:
  * [攻击发起](https://etherscan.io/tx/0x6ed07db1a9fe5c0794d44cd36081d6a6df103fab868cdd75d581e3bd23bc9742)
  * [提款](https://etherscan.io/tx/0xd155207261712c35fa3d472ed1e51bfcd816e616dd4f517fa5959836f5b48569)
---

# 一句话概述
- 由于BalancerV2协议的多个设计漏洞，导致黑客可以左脚踩右脚，在不持有任何资产的场景下，无中生有的发起多笔Swap，最终将BalancerV2池子中的资产全部提取出来

# 本次攻击的整体梳理
- 在本次攻击中，黑客操作可谓是非常的优雅，具有相当的艺术性，后续我们也会逐步和大家一起跟随黑客的思路，看看如何利用一点点的精度损失，撬动整个BalancerV2的巨量资产。
- ![img_3.png](img_3.png)

# 核心攻击交易的梳理
- 以WETH-BPT-osETH为例，该batchSwap总共有120多个swap，但是整体可以认为由3个部分组成：
  - part1: 大量使用BPT购买WETH和osETH，将池子中的WETH-osETH的数量降低到足够低（rounding精度问题matters的程度）
    - 攻击完成前，用BPT购买osETH时，汇率保持在1.04左右
      - ![img_1.png](img_1.png)
  - part2: 通过WETH和osETH的互换，反复的触发rounding精度丢失漏洞，最终大幅度扭曲了对应的BPT price
    - 攻击完成后，用osETH购买BPT时，汇率已经掉到了0.0002左右，一点点osETH就可以购买到大量的BPT
      - ![img_2.png](img_2.png)
  - part3: 用低价的BPT 大量swap（购买） WETH和osETH, 完成了无中生有的操作。
    - attacker在攻击交易完成后，internalBalance记账余额大幅度增加（WETH,BPT,osETH)
    - ![img.png](img.png)

# 本次攻击的思考和探讨
- 在Defi类App的设计中，Rounding相关的精度问题处理一定要慎之又慎
  - 经典的uniswap, dai等都有自己对应的设计考量和优化处理
  - balancerV2的统一精度设计也有可取之处
- 在设计上，尽量还是**fast failed** and **verify first**
  - 本次暴雷，个人认为核心的问题肯定是rounding，但是这个设计机制也是一个很大的问题
  - 如果没有rounding问题，未来可能也会有其他问题发现，只要整个机制允许“无中生有”
- 在web3合约整体的设计上，仍然还是要保持简单 keep it simple
  - 复杂度是一切风险因素的乐园，尤其是在这个AI的时代
- 当整个系统出现异常变更时，稍显中心化的一段时间内，临时停止服务的功能仍然应该是一个保底选项, 尽可能减少次生灾害的发生
  - 比如由社区驱动的提案，或单纯指定几个包含高优先级人员的限制功能的多签

---
# 系列分享计划（暂定 4 Part）

## **🔵 Part 1：Balancer V2 攻击全局解析（不涉及代码）**

- 在不看代码的情况下，从高维度理解整个攻击, 发生了什么事，有哪些对象被牵扯进入，整体上的攻击流程和重点等。

## **🟢 Part 2：前置知识储备详解**
### ComposableStablePool的可组合性
- 某个ComposableStablePool的流动性Token可以作为一个普通token被其他池子当成普通token使用
  - 由于其特有的可叠加的属性，从金融属性上理解，balancer的模型比其他defi更接近现实世界的各类金融产品。
  - 其中的对应的流动性份额Token，就叫做对应的BPT，和池子绑定
    - 如WETH和osETH的兑换池对应的流动性份额token就叫做 WETH/osETH-BPT
    - 不同的pool里的BPT名字和价格均不同,如wstETH/WETH-BPT
  - 如图
    - ![img_4.png](img_4.png)
- 其他类型的Pool
  - ![img_16.png](img_16.png)
  
### 计算前统一精度的rounding设计
- 在关键的_swapGivenOut函数中，会统一处理已有的池子balances，以及swap的amount，按scalingFactors统一精度
  - 首先，像osETH这种rebasingToken, 或者wstETH这种动态兑换比例
  - 其次，对于USDC这种decimals不足18的token，balancerV2会在计算时将其的amount放大到18参与计算
  - ![img_12.png](img_12.png)
- 实际上，本次balancerV2的漏洞本质上也是在于这个scaling缩放过程中，amount被截断导致的。
  - mulDown ![img_13.png](img_13.png)
  - ![img_14.png](img_14.png)
- 此时，被截断的0.98 相比于17本身，就无法再被忽略了
  - ![img_15.png](img_15.png)
  
### invariant D 不变量公式
- 类似于uniswap的x * y = k, 用于自动化的确定amountIn和amountOut,
  - 相同的点
    - 通过公式自动确定in和out
    - 记账余额不可或缺（用于自动化的确认before和after的balance）
  - 但仍然有一些区别
    - 在汇率相近的token兑换中（尤其是稳定币之间），uniswap的公式适用程度就大幅度降低，但stableSwap的表现仍然良好
    - 复杂度问题
    - 支持pool中多个token
- 公式较为复杂，在代码中也有描述，这里可以简单的去理解
  - D = f(sum(balances), A)
- 其中，BPT token的价格可以近似的理解为
  - BPT_price = D / supply
  - 所以相对于黑客来说, 如果黑客能想在supply不变的场景下，大幅度的降低D，那么BPT的价格也就会大幅度降低。
### mint/burn操作被隐形的认为是一个特殊的swap
- 流动性份额token（BPT） In， token0/token1 Out => burn
- 流动性份额token（BPT） Out， token0/token1 in => mint
  - 结合之前提到过的可组合性，就能创造无限可能
- 如图，使用流动性份额BPT（index=1）swap成WETH（index=0），实际上最终走的是burn流程（退出流动性，取回池子中的资产）
  - ![img_6.png](img_6.png)
  - ![img_7.png](img_7.png)
- 最终调用exitSwap
  - ![img_8.png](img_8.png)
    
### internal balance 余额记账设计
- 在BalancerV2的架构设计中，在Vault合约里，会记录每个Pool内部的池子余额
- 设计考量
  - 首先从设计角度来说，balancerV2的Vault集中资金池设计一定是需要一个余额记账机制
    - 否则无法区各个pool中的各个token余额
  - 其次，从自动化Swap的公式角度来说，也是一定需要一个上一个状态的余额
    - 才能判定实际的amountIn和amountOut 
- 实际存储的余额数据
  - 每个pool有自己对应的余额结构
  - 每个pool自己的余额结构包括
    - 池子A中的，token0/1/n 的余额信息，比如cash数量（可用的余额），managed数量（借出给一些defi服务的，不可用余额）.
      - ![img_5.png](img_5.png)
  - 相关代码
    - ![img_9.png](img_9.png)
    - ![img_10.png](img_10.png)
    - 
### 优秀的数据结构设计
  - 在swap操作中，通过index直接更新余额
  - 相比SAFE的owner mapping方案（支持迭代，同时支持用值本身进行查询和更新）
    - 迭代场景: 获取所有的owner列表
    - 值查询和替换的场景: 替换ownerA为ownerB
    - safe的设计
      - ![img_11.png](img_11.png)
  - balancerV2 token balance管理的方案，支持迭代，支持用index进行token余额查询
    - 迭代场景: 计算invariant D这个不变量的时候，需要收集pool中各个token balances（非当前Pool的流动性份额BPT）
    - 值查询和替换的场景：根据index，更新某个token的余额
      - BalancerV2的设计
      - Swaps._processGeneralPoolSwapRequest()
### 先计算，后统一结算
- vault合约的设计允许先计算，再统一结算，本身是一个优化体验节省gas的操作，但是在执行前没有校验用户余额进行verify first
  - **也是本次攻击中隐藏最深的漏洞——设计漏洞，该机制未来可能带来其他严重程度相当的灾害。**
- ![img_17.png](img_17.png)

### BatchSwap流程
- 在part3里跟着黑客的操作，一起梳理。

## **🟣 Part 3：攻击核心梳理**
- 在part 1里我们已经简单提到过了黑客的操作，这里我们就以黑客对于ComposableStablePool(WETH,BPT,osETH)为例
### step 1: 批量兑换，降低池子里的token
- 先跟进梳理一次代码
- 不一次性兑换的原因是可能遇到问题算法问题（手续费），注意选择的givenOut

## **🟢 Part 4：攻击方案分析（Full Walkthrough）**
- 方案梳理和比选 + coding

---

# 参考资料
- [慢雾的分析，较为细致，但也省略了很多细节](https://mp.weixin.qq.com/s/zywPIK08hpy-Ug6rc9Qysw)
- [blockSec的分析](https://mp.weixin.qq.com/s?__biz=MzkyMzI2NzIyMw==&mid=2247490244&idx=1&sn=c71d69c2ea4de29969ec3b11171b5125&chksm=c1e6e33cf6916a2a8939d0fd41f7f3120d745177f4fbdc3ff77c39027895ec36c09bc2f8475f&cur_album_id=3166059377271799813&scene=189#wechat_redirect)