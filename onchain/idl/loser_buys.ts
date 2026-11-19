/**
 * Program IDL in camelCase format in order to be used in JS/TS.
 *
 * Note that this is only a type helper and is not the actual IDL. The original
 * IDL can be found at `target/idl/loser_buys.json`.
 */
export type LoserBuys = {
  "address": "FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC",
  "metadata": {
    "name": "loserBuys",
    "version": "0.1.0",
    "spec": "0.1.0",
    "description": "Created with Anchor"
  },
  "instructions": [
    {
      "name": "createChallenge",
      "docs": [
        "Creates a challenge and its empty prize vault."
      ],
      "discriminator": [
        170,
        244,
        47,
        1,
        1,
        15,
        173,
        239
      ],
      "accounts": [
        {
          "name": "creator",
          "writable": true,
          "signer": true
        },
        {
          "name": "challenge",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  104,
                  97,
                  108,
                  108,
                  101,
                  110,
                  103,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              },
              {
                "kind": "arg",
                "path": "challengeId"
              }
            ]
          }
        },
        {
          "name": "mint"
        },
        {
          "name": "vault",
          "docs": [
            "The prize pool. Only this program can move tokens out of it."
          ],
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  118,
                  97,
                  117,
                  108,
                  116
                ]
              },
              {
                "kind": "account",
                "path": "challenge"
              }
            ]
          }
        },
        {
          "name": "rules",
          "docs": [
            "The challenge's rules and payout terms. Created here, never changed afterwards."
          ],
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  114,
                  117,
                  108,
                  101,
                  115
                ]
              },
              {
                "kind": "account",
                "path": "challenge"
              }
            ]
          }
        },
        {
          "name": "tokenProgram",
          "address": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        },
        {
          "name": "systemProgram",
          "address": "11111111111111111111111111111111"
        }
      ],
      "args": [
        {
          "name": "challengeId",
          "type": "u64"
        },
        {
          "name": "buyIn",
          "type": "u64"
        },
        {
          "name": "startTime",
          "type": "i64"
        },
        {
          "name": "endTime",
          "type": "i64"
        },
        {
          "name": "maxPlayers",
          "type": "u8"
        },
        {
          "name": "oracle",
          "type": "pubkey"
        },
        {
          "name": "rulesHash",
          "type": {
            "array": [
              "u8",
              32
            ]
          }
        },
        {
          "name": "verifier",
          "type": "pubkey"
        },
        {
          "name": "payout",
          "type": {
            "defined": {
              "name": "payoutKind"
            }
          }
        },
        {
          "name": "splitBps",
          "type": {
            "vec": "u16"
          }
        }
      ]
    },
    {
      "name": "endEarly",
      "docs": [
        "Oracle only: ends the challenge now (demo and testing)."
      ],
      "discriminator": [
        109,
        123,
        56,
        49,
        239,
        185,
        241,
        94
      ],
      "accounts": [
        {
          "name": "oracle",
          "signer": true,
          "relations": [
            "challenge"
          ]
        },
        {
          "name": "challenge",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  104,
                  97,
                  108,
                  108,
                  101,
                  110,
                  103,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "challenge.creator",
                "account": "challenge"
              },
              {
                "kind": "account",
                "path": "challenge.challengeId",
                "account": "challenge"
              }
            ]
          }
        }
      ],
      "args": []
    },
    {
      "name": "joinChallenge",
      "docs": [
        "Deposits the buy-in and adds the caller to the player list. Before the start time only,",
        "and only if `expected_rules_hash` is the rules hash fixed at creation."
      ],
      "discriminator": [
        41,
        104,
        214,
        73,
        32,
        168,
        76,
        79
      ],
      "accounts": [
        {
          "name": "player",
          "writable": true,
          "signer": true
        },
        {
          "name": "challenge",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  104,
                  97,
                  108,
                  108,
                  101,
                  110,
                  103,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "challenge.creator",
                "account": "challenge"
              },
              {
                "kind": "account",
                "path": "challenge.challengeId",
                "account": "challenge"
              }
            ]
          }
        },
        {
          "name": "vault",
          "writable": true
        },
        {
          "name": "rules",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  114,
                  117,
                  108,
                  101,
                  115
                ]
              },
              {
                "kind": "account",
                "path": "challenge"
              }
            ]
          }
        },
        {
          "name": "playerToken",
          "docs": [
            "The player's own token account that the buy-in is taken from."
          ],
          "writable": true
        },
        {
          "name": "tokenProgram",
          "address": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        }
      ],
      "args": [
        {
          "name": "expectedRulesHash",
          "type": {
            "array": [
              "u8",
              32
            ]
          }
        }
      ]
    },
    {
      "name": "refund",
      "docs": [
        "Anyone: returns every buy-in when too few players joined or the oracle timed out."
      ],
      "discriminator": [
        2,
        96,
        183,
        251,
        63,
        208,
        46,
        46
      ],
      "accounts": [
        {
          "name": "caller",
          "docs": [
            "Anyone can trigger a refund once it is allowed. They only pay the fee."
          ],
          "signer": true
        },
        {
          "name": "challenge",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  104,
                  97,
                  108,
                  108,
                  101,
                  110,
                  103,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "challenge.creator",
                "account": "challenge"
              },
              {
                "kind": "account",
                "path": "challenge.challengeId",
                "account": "challenge"
              }
            ]
          }
        },
        {
          "name": "vault",
          "writable": true
        },
        {
          "name": "tokenProgram",
          "address": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        }
      ],
      "args": []
    },
    {
      "name": "settle",
      "docs": [
        "Oracle only, after the end time: pays the pool in equal shares to the winners named in the",
        "verifier's signed result (an Ed25519 check must be the instruction right before this one).",
        "Winner takes all, goal and teams formats only."
      ],
      "discriminator": [
        175,
        42,
        185,
        87,
        144,
        131,
        102,
        212
      ],
      "accounts": [
        {
          "name": "oracle",
          "signer": true,
          "relations": [
            "challenge"
          ]
        },
        {
          "name": "challenge",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  104,
                  97,
                  108,
                  108,
                  101,
                  110,
                  103,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "challenge.creator",
                "account": "challenge"
              },
              {
                "kind": "account",
                "path": "challenge.challengeId",
                "account": "challenge"
              }
            ]
          }
        },
        {
          "name": "vault",
          "writable": true
        },
        {
          "name": "rules",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  114,
                  117,
                  108,
                  101,
                  115
                ]
              },
              {
                "kind": "account",
                "path": "challenge"
              }
            ]
          }
        },
        {
          "name": "instructionsSysvar",
          "address": "Sysvar1nstructions1111111111111111111111111"
        },
        {
          "name": "tokenProgram",
          "address": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        }
      ],
      "args": []
    },
    {
      "name": "settleSplit",
      "docs": [
        "Oracle only, after the end time: podium payout. The signed result names the winners in rank",
        "order; `tie_groups` says how many players share each rank. The program works out every share",
        "from the split fixed at creation and pays only if the signed shares are exactly those."
      ],
      "discriminator": [
        3,
        170,
        152,
        217,
        94,
        9,
        9,
        213
      ],
      "accounts": [
        {
          "name": "oracle",
          "signer": true,
          "relations": [
            "challenge"
          ]
        },
        {
          "name": "challenge",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  104,
                  97,
                  108,
                  108,
                  101,
                  110,
                  103,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "challenge.creator",
                "account": "challenge"
              },
              {
                "kind": "account",
                "path": "challenge.challengeId",
                "account": "challenge"
              }
            ]
          }
        },
        {
          "name": "vault",
          "writable": true
        },
        {
          "name": "rules",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  114,
                  117,
                  108,
                  101,
                  115
                ]
              },
              {
                "kind": "account",
                "path": "challenge"
              }
            ]
          }
        },
        {
          "name": "instructionsSysvar",
          "address": "Sysvar1nstructions1111111111111111111111111"
        },
        {
          "name": "tokenProgram",
          "address": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        }
      ],
      "args": [
        {
          "name": "tieGroups",
          "type": "bytes"
        }
      ]
    }
  ],
  "accounts": [
    {
      "name": "challenge",
      "discriminator": [
        119,
        250,
        161,
        121,
        119,
        81,
        22,
        208
      ]
    },
    {
      "name": "rules",
      "discriminator": [
        12,
        186,
        182,
        174,
        196,
        165,
        88,
        15
      ]
    }
  ],
  "events": [
    {
      "name": "challengeCreated",
      "discriminator": [
        166,
        178,
        174,
        178,
        11,
        172,
        98,
        243
      ]
    },
    {
      "name": "challengeEnded",
      "discriminator": [
        248,
        126,
        94,
        14,
        182,
        95,
        205,
        128
      ]
    },
    {
      "name": "challengeRefunded",
      "discriminator": [
        162,
        212,
        42,
        82,
        3,
        200,
        229,
        12
      ]
    },
    {
      "name": "challengeSettled",
      "discriminator": [
        96,
        70,
        232,
        36,
        45,
        207,
        169,
        122
      ]
    },
    {
      "name": "challengeSettledSplit",
      "discriminator": [
        16,
        10,
        247,
        252,
        136,
        217,
        253,
        182
      ]
    },
    {
      "name": "playerJoined",
      "discriminator": [
        39,
        144,
        49,
        106,
        108,
        210,
        183,
        38
      ]
    },
    {
      "name": "rulesLocked",
      "discriminator": [
        130,
        249,
        184,
        194,
        203,
        244,
        42,
        85
      ]
    }
  ],
  "errors": [
    {
      "code": 6000,
      "name": "invalidBuyIn",
      "msg": "Buy-in must be greater than zero"
    },
    {
      "code": 6001,
      "name": "invalidTimes",
      "msg": "Start time must be in the future and before the end time"
    },
    {
      "code": 6002,
      "name": "invalidMaxPlayers",
      "msg": "Max players must be between 2 and 8"
    },
    {
      "code": 6003,
      "name": "challengeNotOpen",
      "msg": "This challenge is already settled or refunded"
    },
    {
      "code": 6004,
      "name": "joinClosed",
      "msg": "Joining closed when the challenge started"
    },
    {
      "code": 6005,
      "name": "challengeFull",
      "msg": "The challenge is full"
    },
    {
      "code": 6006,
      "name": "alreadyJoined",
      "msg": "This player has already joined"
    },
    {
      "code": 6007,
      "name": "notOracle",
      "msg": "Only the oracle can do this"
    },
    {
      "code": 6008,
      "name": "alreadyEnded",
      "msg": "The challenge has already ended"
    },
    {
      "code": 6009,
      "name": "notEnded",
      "msg": "The challenge has not ended yet"
    },
    {
      "code": 6010,
      "name": "notEnoughPlayers",
      "msg": "Not enough players joined; use refund instead"
    },
    {
      "code": 6011,
      "name": "invalidWinners",
      "msg": "Winner list is empty, too long, or has duplicates"
    },
    {
      "code": 6012,
      "name": "winnerNotPlayer",
      "msg": "A winner is not in the player list"
    },
    {
      "code": 6013,
      "name": "refundNotAllowed",
      "msg": "Refund is not allowed yet"
    },
    {
      "code": 6014,
      "name": "wrongNumberOfTokenAccounts",
      "msg": "Expected one token account per recipient, in order"
    },
    {
      "code": 6015,
      "name": "invalidTokenAccount",
      "msg": "A token account has the wrong owner or the wrong token"
    },
    {
      "code": 6016,
      "name": "mathOverflow",
      "msg": "Math overflow"
    },
    {
      "code": 6017,
      "name": "invalidShares",
      "msg": "Need one share per winner, adding up to exactly 100%"
    },
    {
      "code": 6018,
      "name": "invalidRulesHash",
      "msg": "Rules hash must not be empty"
    },
    {
      "code": 6019,
      "name": "invalidSplit",
      "msg": "Payout split must be 2 or 3 places, highest first, adding up to 100% (podium only)"
    },
    {
      "code": 6020,
      "name": "rulesMismatch",
      "msg": "These are not the rules this challenge was created with"
    },
    {
      "code": 6021,
      "name": "wrongPayoutKind",
      "msg": "This payout is not allowed by the challenge's format"
    },
    {
      "code": 6022,
      "name": "sharesNotAsCommitted",
      "msg": "The payout shares are not the ones the challenge's rules give"
    },
    {
      "code": 6023,
      "name": "invalidTieGroups",
      "msg": "Tie groups must cover the paid places and every winner"
    },
    {
      "code": 6024,
      "name": "missingSignatureCheck",
      "msg": "Expected the verifier's Ed25519 signature check right before this instruction"
    },
    {
      "code": 6025,
      "name": "wrongVerifier",
      "msg": "The signature check is not by this challenge's verifier"
    },
    {
      "code": 6026,
      "name": "invalidSignedResult",
      "msg": "The signed result is malformed or for another program, challenge or rules"
    }
  ],
  "types": [
    {
      "name": "challenge",
      "docs": [
        "One weekly challenge and its prize pool."
      ],
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "creator",
            "docs": [
              "Who created the challenge (and paid for the accounts)."
            ],
            "type": "pubkey"
          },
          {
            "name": "challengeId",
            "docs": [
              "Number chosen by the creator so one creator can have many challenges."
            ],
            "type": "u64"
          },
          {
            "name": "oracle",
            "docs": [
              "The only key allowed to end early and to report winners."
            ],
            "type": "pubkey"
          },
          {
            "name": "mint",
            "docs": [
              "Token used for the pool (devnet USDC)."
            ],
            "type": "pubkey"
          },
          {
            "name": "vault",
            "docs": [
              "Token account that holds the pool. Owned by this challenge account."
            ],
            "type": "pubkey"
          },
          {
            "name": "buyIn",
            "docs": [
              "Amount each player deposits, in the token's smallest unit."
            ],
            "type": "u64"
          },
          {
            "name": "startTime",
            "docs": [
              "Joining closes at this time (unix seconds)."
            ],
            "type": "i64"
          },
          {
            "name": "endTime",
            "docs": [
              "Settlement is allowed from this time (unix seconds)."
            ],
            "type": "i64"
          },
          {
            "name": "maxPlayers",
            "type": "u8"
          },
          {
            "name": "players",
            "type": {
              "vec": "pubkey"
            }
          },
          {
            "name": "status",
            "type": {
              "defined": {
                "name": "challengeStatus"
              }
            }
          },
          {
            "name": "scoreHash",
            "docs": [
              "Hash of the final score sheet, set by `settle`. All zeros until then."
            ],
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "bump",
            "type": "u8"
          },
          {
            "name": "vaultBump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "challengeCreated",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "challengeId",
            "type": "u64"
          },
          {
            "name": "oracle",
            "type": "pubkey"
          },
          {
            "name": "mint",
            "type": "pubkey"
          },
          {
            "name": "buyIn",
            "type": "u64"
          },
          {
            "name": "startTime",
            "type": "i64"
          },
          {
            "name": "endTime",
            "type": "i64"
          },
          {
            "name": "maxPlayers",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "challengeEnded",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "endTime",
            "type": "i64"
          }
        ]
      }
    },
    {
      "name": "challengeRefunded",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "playerCount",
            "type": "u8"
          },
          {
            "name": "refundEach",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "challengeSettled",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "winners",
            "type": {
              "vec": "pubkey"
            }
          },
          {
            "name": "poolTotal",
            "type": "u64"
          },
          {
            "name": "payoutEach",
            "type": "u64"
          },
          {
            "name": "scoreHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          }
        ]
      }
    },
    {
      "name": "challengeSettledSplit",
      "docs": [
        "Emitted by `settle_split`: each winner's amount is listed, in the same order as `winners`."
      ],
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "winners",
            "type": {
              "vec": "pubkey"
            }
          },
          {
            "name": "amounts",
            "type": {
              "vec": "u64"
            }
          },
          {
            "name": "poolTotal",
            "type": "u64"
          },
          {
            "name": "scoreHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          }
        ]
      }
    },
    {
      "name": "challengeStatus",
      "type": {
        "kind": "enum",
        "variants": [
          {
            "name": "open"
          },
          {
            "name": "settled"
          },
          {
            "name": "refunded"
          }
        ]
      }
    },
    {
      "name": "payoutKind",
      "docs": [
        "How the pool is paid, fixed at creation (`Rules.payout`)."
      ],
      "type": {
        "kind": "enum",
        "variants": [
          {
            "name": "winnerTakesAll"
          },
          {
            "name": "podium"
          },
          {
            "name": "goal"
          },
          {
            "name": "teams"
          }
        ]
      }
    },
    {
      "name": "playerJoined",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "player",
            "type": "pubkey"
          },
          {
            "name": "playerCount",
            "type": "u8"
          },
          {
            "name": "poolTotal",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "rules",
      "docs": [
        "The rules a challenge was created with. A separate account next to the challenge (seeds",
        "`[\"rules\", challenge]`), so challenges created before it existed keep their layout and can still",
        "be refunded. Written once by `create_challenge`; no instruction can change it afterwards."
      ],
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "rulesHash",
            "docs": [
              "SHA-256 of the canonical JSON ruleset (scoring rules, format, length, verifier...). The ruleset",
              "itself is published offchain so anyone can re-hash it. `join_challenge` must quote this hash."
            ],
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "verifier",
            "docs": [
              "The key whose Ed25519 signature on the result `settle` and `settle_split` require."
            ],
            "type": "pubkey"
          },
          {
            "name": "payout",
            "type": {
              "defined": {
                "name": "payoutKind"
              }
            }
          },
          {
            "name": "splitBps",
            "docs": [
              "Podium only: basis points per place (2 or 3 places, highest first, adding up to 10,000).",
              "Unused places, and every place for other formats, are 0."
            ],
            "type": {
              "array": [
                "u16",
                3
              ]
            }
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "rulesLocked",
      "docs": [
        "Emitted with `ChallengeCreated`: the rules and payout terms are now fixed."
      ],
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "challenge",
            "type": "pubkey"
          },
          {
            "name": "rulesHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "verifier",
            "type": "pubkey"
          },
          {
            "name": "payout",
            "type": {
              "defined": {
                "name": "payoutKind"
              }
            }
          },
          {
            "name": "splitBps",
            "type": {
              "array": [
                "u16",
                3
              ]
            }
          }
        ]
      }
    }
  ],
  "constants": [
    {
      "name": "challengeSeed",
      "docs": [
        "Seed for the challenge account address."
      ],
      "type": "bytes",
      "value": "[99, 104, 97, 108, 108, 101, 110, 103, 101]"
    },
    {
      "name": "maxPlayers",
      "docs": [
        "Most players one challenge can hold."
      ],
      "type": "u8",
      "value": "8"
    },
    {
      "name": "minPlayers",
      "docs": [
        "A challenge needs at least this many players, otherwise it is refunded."
      ],
      "type": "u8",
      "value": "2"
    },
    {
      "name": "proofDomain",
      "docs": [
        "First bytes of every signed result (the Proof of Sweat message). See docs/ARCHITECTURE.md."
      ],
      "type": "bytes",
      "value": "[114, 105, 118, 97, 108, 46, 112, 114, 111, 111, 102, 45, 111, 102, 45, 101, 102, 102, 111, 114, 116, 46, 118, 50]"
    },
    {
      "name": "refundTimeoutSeconds",
      "docs": [
        "If the oracle has not settled this long after the end time, anyone can refund."
      ],
      "type": "i64",
      "value": "259200"
    },
    {
      "name": "rulesSeed",
      "docs": [
        "Seed for the rules account that sits next to each challenge."
      ],
      "type": "bytes",
      "value": "[114, 117, 108, 101, 115]"
    },
    {
      "name": "vaultSeed",
      "docs": [
        "Seed for the token vault that holds the prize pool."
      ],
      "type": "bytes",
      "value": "[118, 97, 117, 108, 116]"
    }
  ]
};
