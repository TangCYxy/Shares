
---
# 攻击总览
- **事件时间**：2025 年11月初
- **受影响服务**：BalancerV2 及其多链部署，其他fork项目等
- **损失规模**：100M+ USD
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
- BalancerV2架构，invariant方案, rounding & Scaling机制等

## **🟣 Part 3：攻击核心梳理**
- 具体的攻击每个步骤说明，包括黑客的攻击代码梳理

## **🟢 Part 4：攻击方案分析（Full Walkthrough）**
- 方案梳理和比选 + coding

---


# 参考资料
- [慢雾的分析，较为细致，但也省略了很多细节](https://mp.weixin.qq.com/s/zywPIK08hpy-Ug6rc9Qysw)
- [blockSec的分析](https://mp.weixin.qq.com/s?__biz=MzkyMzI2NzIyMw==&mid=2247490244&idx=1&sn=c71d69c2ea4de29969ec3b11171b5125&chksm=c1e6e33cf6916a2a8939d0fd41f7f3120d745177f4fbdc3ff77c39027895ec36c09bc2f8475f&cur_album_id=3166059377271799813&scene=189#wechat_redirect)