---
layout: post
title:  "AUTOSAR service model: a big picture"
date:   2024-06-08 9:22:46 +0800
tags: [autosar]
---

The design phase of AUTOSAR communication management can be generalized as following steps: First, a *methodology* is chosen. According to the methodology, *standards* and *protocols* are designed, specifying detailed *behavior*. AUTOSAR vendors and open source organizations *implement* these *standards* and *protocol*. 

AUTOSAR Service Model is based on SOA(service-oriented architecture). According to this service model, AUTOSAR designs the user level API, aka the ara::com::API and the low level communication protocol SOME/IP. ara::com::API and SOME/IP both inherit concept from AUTOSAR service model, so they both have similar concept like service,event, method, etc, even though the meaning of these names varies in its own context. ara::com API can be implemented on other communication protocols, like DDS, instead of SOME/IP. (Interestingly, DDS is not service-oriented.). 

These steps can be illustrated in the following diagram:

| ![Alt text](/assets/images/autosar_service_model.png) | 
|:--:| 
| *AUTOSAR Service Model* |

The soul of the software is the AUTOSAR service model, which defines *service description*:

- A service is interface between service provider and service consumer(SOA)
- AUTOSAR service consists of one or more of following elements:
  - events
  - methods
  - fields

ara::com API and SOME/IP both contain these concepts, but they describe them in different levels:

- SOME/IP is low level *communication oriented* protocol. It emphasize the *transportation* of *data*. It doesn't care about method calls, event handling. It's job is to compose corresponding messages and deliver them to desired target.
- ara::com API is high level *user oriented* standards. It focus on the user side and give detailed requirement on *behavior* of these concepts. For example, ara::com API defines fixed class, method signature and data structures to unify the *behavior* in the eye of the user. ara::com API defines how service provider implement their method logic, how consumer implement their event handler. ara::com API also specifies the execution mechanism, polling or event-driven, for method and event handling. Except for events, methods, fields, ara::com API extends another element: triggers, which does not appear in AUTOSAR service model and SOME/IP. 

Implementation details can be very different for SOME/IP, as long as the implementation adhere to the message format. Implemetentations for ara::com API must use the standard code specified by AUTOSAR, so user does not need to care about the underlying details. The underlying implementation for the ara::com API is called *binding*, and the underlying protocol used for communication is called *driver* or *communication driver*. ara::com API can use SOME/IP as *driver*, which is the AUTOSAR standard. Besides SOME/IP, the ara::com API can also be bound to DDS, whose binding requirement are included in standard.
