---
layout: post
title:  "AUTOSAR Service Model: a big picture"
date:   2023-04-22 19:22:46 +0800
tags: [AUTOSAR]
---

AUTOSAR Service Model is based on SOA(service-oriented architecture). Based on this service model, AUTOSAR defines the user level API, aka the ara::com::API and the low level communication protocol SOME/IP. ara::com::API and SOME/IP both inherit concept from AUTOSAR service model, so they both have similar concept like service、event、method, etc. However, the meaning of these concept in API and SOME/IP is different, and the fact that they originate from the same service model do not make the situation better, on the contrary, worse. The simple explanation is that those concept in SOME/IP is very low level, but in ara::com API, even though with the same name, those concept is user level, which means that they can be implemented on other communication protocols, like DDS, instead of SOME/IP.