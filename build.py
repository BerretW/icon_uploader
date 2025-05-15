docker run -d \
  --network host \
  -v "$PWD/config.json:/app/config.json" \
  -v "$PWD/users.json:/app/users.json" \
  --name icon-app \
  icon-uploader
