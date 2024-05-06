---
layout: post
title:  "ara::com API 解读[Part 2]"
date:   2024-05-05 13:22:46 +0800
tags: [AUTOSAR]
---

[ara::com API](https://www.autosar.org/fileadmin/standards/R23-11/AP/AUTOSAR_AP_EXP_ARAComAPI.pdf)是理解AUTOSAR AP中面向服务架构的入口。无论对于底层BSW开发，模型和代码引擎开发，还是对于上层应用开发，都是需要理解的。可以说ara::com API是应用层开发、BSW开发、模型/代码引擎开发的三者交汇点。理解它非常重要。本文是第一部分。

* toc
{:toc}

# 5 Detailed API description

## 5.3 Proxy Class

> The Proxy class is generated from the SI description of the AUTOSAR meta model.
ara::com does standardize the interface of the generated Proxy class.
>
> The toolchain of an AP product vendor will generate a Proxy implementation class exactly implementing this interface.

---
**NOTE**

Proxy类的API接口是AUTOSAR定义好的，所有的代码引擎都需要生成符合标准要求的API。

---

### 5.3.3 Constructor and Handle Concept


> As you can see in the Listing 5.2 ara::com prescribes the Proxy class to provide a
constructor. This means, that the developer is responsible for creating a proxy instance
to communicate with a possibly remote service.

---
**NOTE**

Proxy类的特点可以总结如下：

- `static`方法用于发现服务
- 应用开发者需要通过发现的`HandleType`创建Proxy类的实例
- 每一个Proxy类的实例只能与一个Skeleton端的服务实例通信

每一个Proxy类的实例都是一个独立的Client（从Skeleton的角度看），它们都有独立的Client ID；在method调用的时候Skeleton端的服务实例通过Client ID来区分这些不同的订阅者。

---

### 5.3.4 Finding Services

通过使用StartFindService和FindService两个`static`方法来发现服务实例：

- StartFindService为异步发现，注册一个回调到COM，每当有新的服务实例被发现，回调会被调用
- FindService为同步发现，直接返回发现结果

这两个API都有两个重载，分别接收` ara::com::InstanceIdentifier`和` ara::core::InstanceSpecifier`，关于这二者的区别详见[Part 1](https://shan-weiqiang.github.io/2024/05/05/ara-com-API-%E8%A7%A3%E8%AF%BB-Part-1.html#481-instance-identifiers-and-instance-specifiers)

#### 5.3.4.1 Auto Update Proxy instance

当已经被发现的服务实例由于各种原因暂停提供服务，而后又重新提供服务后，可以通过自动更新Proxy实例来继续通信，而无需重新走一遍FindService，创建Proxy实例的流程。

此外，允许在StartFindService注册的回调函数中直接使用已经存在的Proxy实例：

- 必须在调用这个回调前，做完自动Proxy实例的更新,这样才能保证Proxy实例的可用性

以上自动更新是通过底层的服务发现模块提供的状态来完成的.

---
**NOTE**

笔者对这个功能持保留意见：

1. 为什么会允许出现在运行时Proxy实例更新的情况？按照文中所说，Proxy实例甚至允许出现底层传输层地址改变的情况,这严重违反了AUTOSAR部署的意义：既然已经是部署，就不能允许在运行时更新部署配置信息。这显然是自相矛盾的。
2. 即便在调用StartFindService注册的回调前自动更新了已经存在的Proxy实例，那也不能保证在调用这个实例的API时对方的服务实例仍然有效。因为这中间存在时间差，而对方服务实例可能远在另外一台机器。

综合以上两点，自动更新Proxy服务实例的功能显得有点过度设计了。

---

### 5.3.5 Events



