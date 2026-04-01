docker run --rm \
  -e NETBOX_URL=https://netbox.int.rusonyx.ru/ \
  -e NETBOX_TOKEN=need set \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server:latest