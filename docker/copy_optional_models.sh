#!/usr/bin/env sh
# The YOLO checkpoint is large and often not committed. If ./models exists in
# the build context it is used; otherwise we create an empty dir so the image
# builds cleanly and the vision/tracking services report `ready:false` with the
# precise missing artifact at runtime.
set -e
if [ -d /srv/models ]; then
  echo "models/ already present"
else
  mkdir -p /srv/models
  echo "NOTE: no YOLO checkpoint baked in — vision/tracking will report unavailable."
fi
