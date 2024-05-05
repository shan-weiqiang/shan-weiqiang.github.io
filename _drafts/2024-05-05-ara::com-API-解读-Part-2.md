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




