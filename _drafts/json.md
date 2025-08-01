---
layout: post
title:  "Type systems: Part III Json"
date:   2025-08-01 9:22:46 +0800
tags: [programming]
---

I talked about types in [Type systems: Part I](https://shan-weiqiang.github.io/2024/07/14/understanding-types.html), and discussed Google Protobuffers in [Type systems: Part II Protobuf Reflection](https://shan-weiqiang.github.io/2025/06/14/protobuf-reflection.html). Today I go deeper into another type, the most common one, json. Json is **inherently** dynamic, even though there are both dynamic and static interpreters.

* toc
{:toc}

## Inherently dynamic

```
{
    "MyMessage": [
        {
            "name": "weiqiang.shan"
        },
        {
            "age": 18
        },
        23,
        "Hello"
    ]
}
```
```
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "MyMessage": {
      "type": "array",
      "minItems": 4,
      "maxItems": 4,
      "items": [
        {
          "type": "object",
          "properties": {
            "name": {
              "type": "string"
            }
          },
          "required": ["name"],
          "additionalProperties": false
        },
        {
          "type": "object",
          "properties": {
            "age": {
              "type": "number"
            }
          },
          "required": ["age"],
          "additionalProperties": false
        },
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": ["MyMessage"],
  "additionalProperties": false
} 
```
```
syntax = "proto3";

package tmp;

// Message representing the root object
message RootMessage {
  repeated MyMessageItem MyMessage = 1;
}

// Union type to represent the mixed array items
message MyMessageItem {
  oneof value {
    NameObject name_value = 1;
    AgeObject age_value = 2;
    int32 number_value = 3;
    string string_value = 4;
  }
}

// Object with name property
message NameObject {
  string name = 1;
}

// Object with age property  
message AgeObject {
  int32 age = 1;
} 

// Pseudo code

message {
    repeated MyMessage [
        message  {
            string name = 1;
          },
          message  {
            int32 age = 1;
        },
        int32  = 3;
        string  = 4;
    ]
}
```
- json schema define types without names, all `properties` are expanded in-place. Properties have names, but without types, their types are descripted in-place.
- whenever you create a json, there is a cooresponding schema, this schema can be seen as a type. so json is dynamic in nature

