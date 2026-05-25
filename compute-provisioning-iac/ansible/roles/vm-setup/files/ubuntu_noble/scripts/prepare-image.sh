#!/bin/bash

# Post-processor : doing something with the build image.

name=$IMAGE_NAME
version=$IMAGE_VERSION
image="${name}-${version}"
path_dir="artifacts/"
path_image="artifacts/${image}"

file_ext=$IMAGE_FORMAT
if [ "$format" = "raw" ]; then
  file_ext="img"
fi

# go to the artifact folder
cd ${path_dir}

# rename the image, compute shasum
mv packer-${image} ${image}.${file_ext}
sha256sum ${image}.${file_ext} > ${image}.${file_ext}.sha256sum