# CollectionBlockarr

Stop Jellyfin from automatically creating unwanted TMDb collections—without disabling automatic collections for the sagas you actually want.

## Why It Exists & How It Works
When Jellyfin's automatic collection grouping is active, TMDb metadata frequently turns standalone movies, cash-grab sequels, and unwanted spin-offs into clutter collections—while disabling auto-collections globally forces you to build every legitimate saga by hand, and manually deleting collections in Jellyfin only lasts until the next library scan rebuilds them.

CollectionBlockarr solves that cleanly in a single zero-dependency Python container:
- **Strips `TmdbCollection` IDs:** Removes the `TmdbCollection` provider ID from every movie inside a blocked collection before deleting the box set, so future library scans never rebuild it.
- **Real-Time Webhook + Startup Sweep:** Intercepts newly added or updated items via Jellyfin's Webhook plugin and runs an automatic cleanup sweep on every container start.
- **True Instant Restore:** Saves lightweight JSON metadata snapshots (`backups/`) so unblocking a collection immediately recreates the exact grouped collection in Jellyfin.
- **Portable Full-State Backup:** One-click `Export JSON` and `Import JSON` bundle your blocklist, restore snapshots, and connection settings into a single file.

---

## 2-Minute Docker Setup
*Works across any NAS or Linux host running Docker (UGREEN UGOS, Synology, TrueNAS, Unraid, Debian/Ubuntu) and deploys cleanly via CLI, Portainer, or Dockhand.*

### 1. Create Folder & `docker-compose.yml`
Place `collection_killer.py` and `docker-compose.yml` in a folder on your server (for example, `/docker/collectionblockarr`), then start the container:

```bash
docker compose up -d
```

### 2. First-Time Login & Jellyfin API Key
1. Open `http://<your-server-ip>:8099` in your browser and complete the one-time admin account setup.
2. In Jellyfin, go to **Dashboard -> API Keys**, create a key named `CollectionBlockarr`, and paste it alongside your Jellyfin URL (e.g. `http://192.168.1.50:8096`) inside **Settings**.

### 3. Enable Real-Time Webhook Interception
1. In Jellyfin, open **Dashboard -> Plugins -> Webhook** (install from the official Jellyfin catalog if needed).
2. Add a **Generic Destination**:
   - **Webhook URL:** `http://<your-server-ip>:8099/webhook`
   - **Notification Type:** Check **Item Added** and **Item Updated**
   - **Send All Properties:** Enabled
3. Click **Test** in CollectionBlockarr's top status bar to confirm all health pills read green.

## Changelog
See [CHANGELOG.md](CHANGELOG.md) for full release history.

- **v1.0.1 (2026-11-27):** Added 60s background sweep thread, fixed 5-minute health retest timer crash, and added in-app Changelog modal + GitHub link.
- **v1.0.0 (2026-11-26):** Initial release.

---

*Conceived, directed, and battle-tested on a live home NAS by **MoreBloodWine** — built and refined in collaboration with **Gemini** (Google AI).*
