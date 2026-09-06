# CryptoOSINT MCP Server

Exposes the CryptoOSINT investigation engines as **Model Context Protocol (MCP)** tools so AI
agents (Claude Desktop, Cursor, Zed, or any MCP client) can drive investigations directly.

## Tools exposed

| Tool | Engine | What it does |
|---|---|---|
| `screen_sanctions_address` | `sanctions_engine` | Screen an address vs OFAC + multi-jurisdiction lists |
| `search_sanctions_name` | `sanctions_engine` | Fuzzy name/alias search (catches misspellings) |
| `identify_vasp` | `vasp_directory` | Know-Your-VASP attribution for an address |
| `generate_sar` | `regulatory_reports` | Draft a Suspicious Activity Report (auto-enriched) |
| `generate_travel_rule` | `regulatory_reports` | Draft a FATF Travel Rule / IVMS101 message |
| `demix_tornado_cash` | `demix_engine` | Pair Tornado Cash deposits ↔ withdrawals |
| `demix_bridge` | `demix_engine` | Reconcile cross-chain bridge transfers |
| `investigate_nft_tron` | `nft_tron_engine` | Full NFT/TRON investigation incl. OpenSea lookup |

## Install

```bash
cd backend
pip install -r requirements.txt   # installs fastmcp
```

## Run

Local (stdio — for Claude Desktop / Cursor):
```bash
python mcp_server.py
```

Remote (HTTP — for networked MCP clients):
```bash
python mcp_server.py --remote --port 8002
```

## Configure Claude Desktop

Add to `%APPDATA%/Claude/claude_desktop_config.json` (Windows) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "cryptoosint": {
      "command": "python",
      "args": ["C:/Users/drspy/Desktop/CryptoOSINT-Production/backend/mcp_server.py"]
    }
  }
}
```

## Configure Cursor

Add to `mcp.json`:

```json
{
  "mcpServers": {
    "cryptoosint": {
      "command": "python",
      "args": ["C:/Users/drspy/Desktop/CryptoOSINT-Production/backend/mcp_server.py"]
    }
  }
}
```

Once connected you can ask the agent things like:
*"Screen 0x8589… for sanctions"*, *"Is this address a known exchange?"*,
*"Draft a SAR for this wallet"*, or *"Demix these Tornado Cash withdrawals."*
