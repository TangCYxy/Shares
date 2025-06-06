pragma solidity >=0.8.0 <0.9.0;

// This is the ETH/ERC20/NFT multisig contract for Ownbit.
//
// For 2-of-3 multisig, to authorize a spend, two signtures must be provided by 2 of the 3 owners.
// To generate the message to be signed, provide the destination address and
// spend amount (in wei) to the generateMessageToSign method.
// The signatures must be provided as the (v, r, s) hex-encoded coordinates.
// The S coordinate must be 0x00 or 0x01 corresponding to 0x1b and 0x1c, respectively.
//
// WARNING: The generated message is only valid until the next spend is executed.
//          after that, a new message will need to be calculated.
//
//
// Accident Protection MultiSig, rules:
//
// Participants must keep themselves active by submitting transactions. 
// Not submitting any transaction within 3,000,000 ETH blocks (roughly 416 days) will be treated as wallet lost (i.e. accident happened), 
// other participants can still spend the assets as along as: valid signing count >= Min(mininual required count, active owners).
//
// INFO: This contract is ERC20/ERC721/ERC1155 compatible.
// This contract can both receive ETH, ERC20 and NFT (ERC721/ERC1155) tokens.
// Last update time: 2023-06-04.
// copyright@ownbit.io

contract OwnbitMultiSig {
    
  uint constant public MAX_OWNER_COUNT = 9;
  uint constant public MAX_INACTIVE_TIME = 416 days; 

  // The N addresses which control the funds in this contract. The
  // owners of M of these addresses will need to both sign a message
  // allowing the funds in this contract to be spent.
  mapping(address => uint256) private ownerActiveTimeMap; //uint256 is the active timestamp(in secs) of this owner
  address[] private owners;// owner list .size = 3
  uint private required; // threshold = 2

  // The contract nonce is not accessible to the contract so we
  // implement a nonce-like variable for replay protection.
  uint256 private spendNonce = 0;
    mapping(address => bool) nonceUsed;
    // nonce -> eoa链在管理的账户. 0, 1,
//    我的签名，任何时候都可以校验通过，避免不停得拿成功的签名执行不同的交易。
//    owner，nonce（双花），链信息（evm多个链，没个链上地址是一样的，防止多链重放），有效时间（usdc，validAfter和validBefore）
  
  // An event sent when funds are received.
  event Funded(address from, uint value);
  
  // An event sent when an spendAny is executed.
  event Spent(address to, uint value);

  modifier validRequirement(uint ownerCount, uint _required) {
    require (ownerCount <= MAX_OWNER_COUNT
            && _required <= ownerCount
            && _required >= 1);
    _;
  }
  
  /// @dev Contract constructor sets initial owners and required number of confirmations.
  /// @param _owners List of initial owners.
  /// @param _required Number of required confirmations.
  constructor(address[] memory _owners, uint _required) validRequirement(_owners.length, _required) {
    for (uint i = 0; i < _owners.length; i++) {
        //owner should be distinct, and non-zero
        if (ownerActiveTimeMap[_owners[i]] > 0 || _owners[i] == address(0x0)) {
            revert();
        }
        ownerActiveTimeMap[_owners[i]] = block.timestamp;
    }
    owners = _owners;
    required = _required;
  }

  // The fallback function for this contract.
    // a send b 1 eth/ b contract selfdestruct / a access b contract methodA, methodA is not defined in b
  fallback() external payable {
    if (msg.value > 0) { //eth, pol
        emit Funded(msg.sender, msg.value);
    }
  }
  
  // @dev Returns list of owners.
  // @return List of owner addresses.
    // read only
  function getOwners() public view returns (address[] memory) {
    return owners;
  }
    
  function getSpendNonce() public view returns (uint256) {
    return spendNonce;
  }
    
  function getRequired() public view returns (uint) {
    return required;
  }
  
  //return the active timestamp of this owner
  function getOwnerActiveTime(address addr) public view returns (uint256) {
    return ownerActiveTimeMap[addr];
  }

  // Generates the message to sign given the output destination address and amount.
  // includes this contract's address and a nonce for replay protection.
  // One option to independently verify: https://leventozturk.com/engineering/sha3/ and select keccak
  function generateMessageToSign(address destination, uint256 value, bytes memory data) private view returns (bytes32) {
    //the sequence must match generateMultiSigV3 in JS
    bytes32 message = keccak256(abi.encodePacked(address(this), destination, value, data, spendNonce));
    return message;
  }
  
  function _messageToRecover(address destination, uint256 value, bytes memory data) private view returns (bytes32) {
    bytes32 hashedUnsignedMessage = generateMessageToSign(destination, value, data);
    bytes memory prefix = "\x19Ethereum Signed Message:\n32";// personalSign前缀，
    return keccak256(abi.encodePacked(prefix, hashedUnsignedMessage));
  }
  
  //destination can be a normal address or a contract address, such as ERC20 contract address.
  //value is the wei transferred to the destination.
  //data for transfer ether: 0x
  //data for transfer erc20 example: 0xa9059cbb000000000000000000000000ac6342a7efb995d63cc91db49f6023e95873d25000000000000000000000000000000000000000000000000000000000000003e8
  //data for transfer erc721 example: 0x42842e0e00000000000000000000000097b65ad59c8c96f2dd786751e6279a1a6d34a4810000000000000000000000006cb33e7179860d24635c66850f1f6a5d4f8eee6d0000000000000000000000000000000000000000000000000000000000042134
  //data can contain any data to be executed.
    // ecdsa签名 eth/polygon/btc. 32 r, 32 s, 1 v
    // eddsa签名 r, s
    // 1个请求里，提交了所有需要签名的owner的signature.
  function spend(address destination, bytes32 nonce, uint256 value, uint8[] memory vs, bytes32[] memory rs, bytes32[] memory ss, bytes calldata data) external {
    require(destination != address(this), "Not allow sending to yourself");
      require(nonceUsed[nonce] == false, "Nonce already used");
    require(_validSignature(destination, value, vs, rs, ss, data), "invalid signatures");
    spendNonce = spendNonce + 1;
      nonceUsed[nonce] = true;
    //transfer tokens from this contract to the destination address
    (bool sent,) = destination.call{value: value}(data);
    if (sent) {
        emit Spent(destination, value);
    }
  }
  
  //send a tx from the owner address to active the owner
  //Allow the owner to transfer some ETH, although this is not necessary.
    // ownerable2Step(). a transfer ownership b, ensure b address is correct. openzeppelin
  function active() external payable {
    require(ownerActiveTimeMap[msg.sender] > 0, "Not an owner");
    ownerActiveTimeMap[msg.sender] = block.timestamp;
  }
  
  function getRequiredWithoutInactive() public view returns (uint) {
    uint activeOwner = 0;  
    for (uint i = 0; i < owners.length; i++) {
        //if the owner is active
        if (ownerActiveTimeMap[owners[i]] + MAX_INACTIVE_TIME >= block.timestamp) {
            activeOwner++;
        }
    }
    //active owners still equal or greater then required
    if (activeOwner >= required) {
        return required;
    }
    //active less than required, all active must sign
    if (activeOwner >= 1) {
        return activeOwner;
    }
    //at least one sign.
    return 1;
  }

  // Confirm that the signature triplets (v1, r1, s1) (v2, r2, s2) ...
  // authorize a spend of this contract's funds to the given destination address.
  function _validSignature(address destination, uint256 value, uint8[] memory vs, bytes32[] memory rs, bytes32[] memory ss, bytes memory data) private returns (bool) {
    require(vs.length == rs.length);
    require(rs.length == ss.length);
    require(vs.length <= owners.length);
    require(vs.length >= getRequiredWithoutInactive());
    bytes32 message = _messageToRecover(destination, value, data);
    address[] memory addrs = new address[](vs.length);
    for (uint i = 0; i < vs.length; i++) {
        //recover the address associated with the public key from elliptic curve signature or return zero on error 
        addrs[i] = ecrecover(message, vs[i]+27, rs[i], ss[i]);
    }
      // 0/1 曲线上选择点 s, n - s
    require(_distinctOwners(addrs));
    _updateActiveTime(addrs); //update addrs' active timestamp
    
    //check again, this is important to prevent inactive owners from stealing the money.
    require(vs.length >= getRequiredWithoutInactive(), "Active owners updated after the call, please call active() before calling spend.");
    
    return true;
  }
  
  // Confirm the addresses as distinct owners of this contract.
  function _distinctOwners(address[] memory addrs) private view returns (bool) {
    if (addrs.length > owners.length) {
        return false;
    }
    for (uint i = 0; i < addrs.length; i++) {
        //> 0 means one of the owner
        if (ownerActiveTimeMap[addrs[i]] == 0) {
            return false;
        }
        //address should be distinct
        for (uint j = 0; j < i; j++) {
            if (addrs[i] == addrs[j]) {
                return false;
            }
        }
    }
    return true;
  }
  
  //update the active block number for those owners
  function _updateActiveTime(address[] memory addrs) private {
    for (uint i = 0; i < addrs.length; i++) {
        //only update active timestamp for owners
        if (ownerActiveTimeMap[addrs[i]] > 0) {
            ownerActiveTimeMap[addrs[i]] = block.timestamp;
        }
    }
  }
    // oscar, ted, kira / 2
    // offline transfer to niko. oscar, ted. nonce=0, nonce=1, nonce=2. batch(tx1, tx2, tx3) = packagedTx1
    // gas relay submit tx on chain -> spend(niko.address, data, amount);

  //support ERC721 safeTransferFrom
  function onERC721Received(address _operator, address _from, uint256 _tokenId, bytes calldata _data) external returns(bytes4) {
      return bytes4(keccak256("onERC721Received(address,address,uint256,bytes)"));
  }

  function onERC1155Received(address _operator, address _from, uint256 _id, uint256 _value, bytes calldata _data) external returns(bytes4) {
      return bytes4(keccak256("onERC1155Received(address,address,uint256,uint256,bytes)"));
  }
}
