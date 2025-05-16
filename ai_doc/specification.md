# 程序说明书：Tailscale设备自动同步到Cloudflare DNS工具

## 概述

本程序旨在实现一种自动化工具，将 **Tailscale** 中注册的设备信息同步到 **Cloudflare DNS** 中。具体功能是当 Tailscale 中新增设备时，自动在 Cloudflare 的 DNS 设置中创建一个 A 类型记录，将设备名称映射到其在 Tailscale 网络中的内部 IP 地址。

程序设计灵活，支持用户通过配置文件自定义参数（如 API Token、域名等），并提供测试指令便于开发者验证功能。项目采用 Python 3 开发，使用 **uv** 进行环境管理，并按照成熟的开源项目标准组织代码结构。

---

## 功能描述

### 核心功能

1. **设备同步**：
   - 从 Tailscale 获取当前网络中的设备列表及其内部 IP 地址。
   - 在 Cloudflare DNS 中为每个设备创建一条 A 类型记录，记录名格式如：`<设备名称>.ts.<用户域名>`，指向相应的 Tailscale 内部 IP。

2. **设备更新检测**：
   - 自动检测 Tailscale 中设备的新增或变更。
   - 针对变更设备，更新 Cloudflare DNS 中的对应记录。

3. **设备删除**：
   - 当设备从 Tailscale 网络中移除时，自动删除 Cloudflare DNS 中对应的 A 记录。

### 配置管理

- **灵活配置**：
  - 用户通过配置文件（如 `config.yaml` 或 `.env` 文件）设置以下参数：
    - Tailscale API Token。
    - Cloudflare API Token。
    - Cloudflare 管理的域名（如 `abc.com`）。
    - 子域名前缀（如 `ts`，默认为 `ts`）。
    - 其他辅助参数（如同步周期、日志级别等）。

### 测试指令

- 提供便于测试的功能指令：
  - 清理 Cloudflare DNS 中指定的 A 记录（如清除所有 `*.ts.<用户域名>` 记录）。
  - 手动触发一次同步操作。
  - 获取并打印当前 Tailscale 设备列表。
  - 验证配置文件的有效性（如检查 API Token 是否有效）。

### 开源项目结构

- 按照成熟开源项目的标准组织，包括：
  - **目录结构**：清晰划分核心代码、配置、测试、文档等。
  - **README 文件**：详细描述项目功能、使用方法、配置说明以及开发指南。
  - **.gitignore 文件**：排除敏感信息（如 API Token）及不必要的文件（如生成的缓存文件）。
  - **测试用例**：覆盖核心功能的单元测试和集成测试。
  - **开源协议**：如 MIT、Apache 2.0 等。

### 环境管理

- 使用 **uv** 工具进行 Python 虚拟环境和依赖管理。
- 为开发和生产环境分别配置依赖项（如 `requirements-dev.txt` 和 `requirements.txt`）。

---

## 技术细节

### 1. **Tailscale API**

Tailscale 提供了一组 RESTful API，用于查询设备信息。需要通过以下步骤获取设备列表：

- **认证**：
  - 使用用户提供的 API Token （通过配置文件加载）。
  - 参考 Tailscale API 文档，确保 Token 具备读取设备信息的权限。

- **获取设备列表**：
  - 调用 Tailscale 的 `/devices` 或类似端点，获取所有设备的名称和内部 IP 地址。
  - 解析返回的 JSON 数据，提取设备名称和 IP。

### 2. **Cloudflare API**

Cloudflare 提供了 DNS 管理的 RESTful API。需要利用以下功能完成 DNS 记录的同步：

- **认证**：
  - 使用用户提供的 API Token （通过配置文件加载）。
  - 参考 Cloudflare API 文档，确保 Token 拥有 DNS 管理权限。

- **管理 DNS 记录**：
  - **查询记录**：通过 Cloudflare API 查询现有的 DNS 记录。
  - **创建记录**：为新增的设备创建 A 类型记录。
  - **更新记录**：当设备的 IP 地址发生更改时，更新对应的记录。
  - **删除记录**：当设备从 Tailscale 中移除时，删除对应的记录。

### 3. **配置文件**

- 用户需要提供一个配置文件（如 `config.yaml`），示例内容如下：

```yaml
tailscale:
  api_token: "your-tailscale-api-token"

cloudflare:
  api_token: "your-cloudflare-api-token"
  domain: "abc.com"
  subdomain_prefix: "ts"

sync:
  interval_seconds: 300  # 同步周期，单位为秒
  log_level: "INFO"
```

- 程序启动时自动读取配置文件，验证其合法性。

### 4. **自动化测试**

- **单元测试**：
  - Mock Tailscale 和 Cloudflare API，测试核心逻辑。
  - 测试配置文件解析、错误处理等功能。

- **集成测试**：
  - 在测试环境中调用真实的 Tailscale 和 Cloudflare API，验证功能完整性。

- **测试工具链**：
  - 使用 `pytest` 作为测试框架，并结合 `pytest-mock` 模块进行 Mock。

---

## 项目目录结构

```plaintext
project-root/
│
├── src/                        # 核心代码
│   ├── __init__.py
│   ├── tailscale.py            # Tailscale API 交互模块
│   ├── cloudflare.py           # Cloudflare API 交互模块
│   ├── config.py               # 配置文件解析模块
│   ├── sync.py                 # 设备同步逻辑
│   └── utils.py                # 通用工具函数
│
├── tests/                      # 测试用例
│   ├── test_tailscale.py
│   ├── test_cloudflare.py
│   ├── test_config.py
│   └── test_sync.py
│
├── config.yaml                 # 配置文件示例
├── README.md                   # 项目介绍文档
├── requirements.txt            # 生产依赖
├── requirements-dev.txt        # 开发依赖（如测试工具）
├── .gitignore                  # 忽略规则
├── LICENSE                     # 开源协议文件
└── setup.py                    # 安装脚本
```

---

## 使用指南

### 1. 环境准备

- 安装 **uv**：
  ```bash
  pip install uv
  ```

- 创建虚拟环境并安装依赖：
  ```bash
  uv start
  uv --dev install
  ```

### 2. 配置文件

- 复制 `config.yaml` 示例文件并填写必要参数。

### 3. 启动程序

这个程序最好是在tailscale的设备上运行，确保可以访问tailscale和cloudflare的API。

- 手动运行同步：
  ```bash
  python src/sync.py
  ```

- 启动定时同步（守护模式）：
  ```bash
  python src/sync.py --watch
  ```

### 4. 测试

- 运行所有测试用例：
  ```bash
  pytest
  ```
---

## API参考文档

- [Tailscale API 文档](https://tailscale.com/kb/1101/api?q=api)
- [Cloudflare API 文档](https://developers.cloudflare.com/api/)

### 1. Tailscale API overview

https://tailscale.com/api#description/overview

### 2. Tailscale API devices

https://tailscale.com/api#tag/devices/GET/tailnet/{tailnet}/devices

```bash
curl --request GET \
  --url https://api.tailscale.com/api/v2/tailnet/example.com/devices \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

Response:

```json
{
  "devices": [
    {
      "addresses": [
        [
          "100.87.74.78",
          "fd7a:115c:a1e0:ac82:4843:ca90:697d:c36e"
        ]
      ],
      "id": "92960230385",
      "nodeId": "n292kg92CNTRL",
      "user": "amelie@example.com",
      "name": "pangolin.tailfe8c.ts.net",
      "hostname": "pangolin",
      "clientVersion": "v1.36.0",
      "updateAvailable": false,
      "os": "linux",
      "created": "2022-12-01T05:23:30Z",
      "lastSeen": "2022-12-01T05:23:30Z",
      "keyExpiryDisabled": false,
      "expires": "2023-05-30T04:44:05Z",
      "authorized": false,
      "isExternal": false,
      "machineKey": "",
      "nodeKey": "nodekey:01234567890abcdef",
      "blocksIncomingConnections": false,
      "enabledRoutes": [
        "10.0.0.0/16",
        "192.168.1.0/24"
      ],
      "advertisedRoutes": [
        "10.0.0.0/16",
        "192.168.1.0/24"
      ],
      "clientConnectivity": {
        "endpoints": [
          "199.9.14.201:59128",
          "192.68.0.21:59128"
        ],
        "latency": {
          "Dallas": {
            "latencyMs": 60.463043
          },
          "New York City": {
            "preferred": true,
            "latencyMs": 31.323811
          }
        },
        "mappingVariesByDestIP": false,
        "clientSupports": {
          "hairPinning": false,
          "ipv6": false,
          "pcp": false,
          "pmp": false,
          "udp": false,
          "upnp": false
        }
      },
      "tags": [
        "tag:golink"
      ],
      "tailnetLockError": "",
      "tailnetLockKey": "",
      "postureIdentity": {
        "serialNumbers": [
          "CP74LFQJXM"
        ]
      }
    }
  ]
}
```

### 3. Cloudflare API dns settings

https://developers.cloudflare.com/api/resources/dns/

```bash
curl https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_settings \
    -X PATCH \
    -H 'Content-Type: application/json' \
    -H "X-Auth-Email: $CLOUDFLARE_EMAIL" \
    -H "X-Auth-Key: $CLOUDFLARE_API_KEY" \
    -d '{
      "ns_ttl": 86400,
      "zone_mode": "dns_only"
    }'
```

Response:

```json
{
  "errors": [
    {
      "code": 1000,
      "message": "message",
      "documentation_url": "documentation_url",
      "source": {
        "pointer": "pointer"
      }
    }
  ],
  "messages": [
    {
      "code": 1000,
      "message": "message",
      "documentation_url": "documentation_url",
      "source": {
        "pointer": "pointer"
      }
    }
  ],
  "success": true,
  "result": {
    "flatten_all_cnames": false,
    "foundation_dns": false,
    "internal_dns": {
      "reference_zone_id": "reference_zone_id"
    },
    "multi_provider": false,
    "nameservers": {
      "type": "cloudflare.standard",
      "ns_set": 1
    },
    "ns_ttl": 86400,
    "secondary_overrides": false,
    "soa": {
      "expire": 604800,
      "min_ttl": 1800,
      "mname": "kristina.ns.cloudflare.com",
      "refresh": 10000,
      "retry": 2400,
      "rname": "admin.example.com",
      "ttl": 3600
    },
    "zone_mode": "dns_only"
  }
}
```

---

通过上述说明书，大模型可以更高效地实现该项目的目标功能。