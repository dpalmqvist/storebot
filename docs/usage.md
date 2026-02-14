# Usage Guide

## Starting the Bot

```bash
storebot
```

The bot starts, connects to Telegram, and begins listening for messages. The first time you send `/start`, your chat ID is registered for admin notifications (order alerts, scout digests, etc.).

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and introduction |
| `/help` | Show available commands and capabilities |
| `/new` | Start a new conversation (resets history) |
| `/orders` | Check for and display new orders |
| `/scout` | Manually trigger all saved search scouting |
| `/marketing` | Show listing performance report |
| `/rapport` | Business report (summary, profitability, inventory) |

Send any **text message** to chat with the agent. Send a **photo** and the agent will analyze it with vision, describe what it sees, and offer to create a product listing.

## Workflows

### Product Listing

The full flow from photo to published listing:

1. **Send a photo** — The agent analyzes the image and describes what it sees
2. **Create product** — The agent creates a product record with details (condition, materials, era, dimensions, source, acquisition cost, weight)
3. **Price check** — The agent searches Tradera and Blocket for comparable items and suggests a price range based on market data (min/max/mean/median/quartiles)
4. **Draft listing** — The agent generates a Swedish title and description, selects a Tradera category, looks up shipping options based on product weight, and creates a draft listing for review
5. **Review & approve** — You review the draft and approve or reject it. Rejected drafts can be edited and re-submitted
6. **Publish** — Approved listings are published to Tradera: images are optimized and uploaded, the listing is created via the SOAP API, and the database is updated

All listings start as **drafts** requiring explicit approval before publishing.

### Order Fulfillment

The bot automatically polls Tradera for new orders (configurable interval, default 30 minutes). When a sale is detected:

1. **Import** — The order is imported, product status updated to "sold", listing status updated to "sold"
2. **Notification** — You receive a Telegram message with order details (buyer, amount, product)
3. **Sale voucher** — Create an accounting voucher with automatic VAT/revenue/fee calculation
4. **Shipping label** — Generate a PostNord shipping label (requires product weight). Service options: MyPack Collect (19), MyPack Home (17), Postpaket (18)
5. **Mark shipped** — Mark the order as shipped (Tradera notification sent, tracking number persisted)
6. **Feedback** — The agent suggests a positive Swedish comment (max 80 characters) for you to approve

Use `/orders` to manually check for new orders at any time.

### Sourcing with Scout

The Scout Agent monitors marketplaces for sourcing opportunities:

1. **Create saved searches** — Tell the agent what you're looking for (e.g., "antik byrå under 500 kr") and it creates a saved search with keywords, category, price filters, and platform (Tradera, Blocket, or both)
2. **Daily digest** — Every morning (default 08:00), the bot runs all saved searches and sends a digest of new finds
3. **Manual trigger** — Use `/scout` to run all saved searches immediately
4. **Deduplication** — Items already seen are filtered out automatically
5. **Manage searches** — Update or deactivate saved searches through conversation

### Analytics & Reporting

- `/rapport` — Business summary with revenue, costs, gross profit, margin, items sold, inventory status, and average time to sale
- `/marketing` — Listing performance report across all active listings (views, bids, watchers, conversion funnel)
- **Period comparison** — Automatic weekly comparison sent every Sunday at 18:00 (current period vs previous)
- **Profitability** — Net profit per product, aggregated by category and sourcing channel
- **Inventory** — Stock value, status distribution, aging analysis (0-7d, 8-14d, 15-30d, 30+d)
- **Sourcing analysis** — ROI per sourcing channel (flea market, estate sale, Tradera, etc.)

### Accounting

Storebot includes local double-entry bookkeeping using the Swedish BAS-kontoplan:

- **Sale vouchers** — Automatically calculated with revenue (3001), VAT (2611), and marketplace fees (6590)
- **Manual vouchers** — Create vouchers for any transaction (purchases, expenses, etc.) — debit and credit must balance
- **PDF export** — Export individual or batch voucher PDFs for manual entry into your external accounting system
- **VAT handling** — Moms at 25% on goods; registration required if turnover > 80,000 kr/year

## Agent Tools

The Claude agent has access to 44 tools organized by domain:

| Domain | Count | Tools |
|--------|-------|-------|
| **Search** | 3 | `search_tradera`, `search_blocket`, `get_blocket_ad` |
| **Products** | 6 | `create_product`, `save_product_image`, `search_products`, `get_product_images`, `archive_product`, `unarchive_product` |
| **Listings** | 9 | `create_draft_listing`, `list_draft_listings`, `get_draft_listing`, `update_draft_listing`, `approve_draft_listing`, `reject_draft_listing`, `publish_listing`, `get_categories`, `get_shipping_options` |
| **Orders** | 8 | `check_new_orders`, `list_orders`, `get_order`, `create_sale_voucher`, `mark_order_shipped`, `create_shipping_label`, `list_orders_pending_feedback`, `leave_feedback` |
| **Accounting** | 2 | `create_voucher`, `export_vouchers` |
| **Pricing** | 1 | `price_check` |
| **Scout** | 6 | `create_saved_search`, `list_saved_searches`, `update_saved_search`, `delete_saved_search`, `run_saved_search`, `run_all_saved_searches` |
| **Marketing** | 4 | `refresh_listing_stats`, `analyze_listing`, `get_performance_report`, `get_recommendations` |
| **Analytics** | 5 | `business_summary`, `profitability_report`, `inventory_report`, `period_comparison`, `sourcing_analysis` |

All agent actions are logged to the `agent_actions` table for full audit trail.

## Scheduled Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| Order polling | Every 30 min (configurable) | Polls Tradera for new orders, sends notifications |
| Scout digest | Daily at 08:00 (configurable) | Runs all saved searches, sends digest of new finds |
| Marketing refresh | Daily at 07:00 (configurable) | Refreshes listing stats, sends high-priority recommendations |
| Weekly comparison | Sundays at 18:00 | Period comparison report (this week vs last) |

Scheduled jobs require the bot to have received at least one `/start` command to register the owner chat ID for notifications.

## Human-in-the-Loop Design

Storebot is designed with safety-first automation:

- **Listings** — All listings start as drafts requiring explicit approval before publishing
- **Shipping** — Orders are never marked as shipped without owner confirmation
- **Feedback** — Buyer feedback is never sent without owner approval of the text
- **Vouchers** — Sale vouchers are created on request, not automatically
- **Pricing** — Price suggestions are advisory; the owner sets final pricing

## Conversation History

- Messages are persisted per chat in SQLite
- Configurable history length (default: 20 messages) and timeout (default: 60 minutes)
- Image file paths are stored (not base64) and re-encoded when loading history
- Use `/new` to manually reset the conversation
