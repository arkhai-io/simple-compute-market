# The Helm evidence kind

The `helm` kind shows that the tree under validation deploys: its images built, the
chart installed into the change's own namespace on the local cluster, and the chart's
tests and served scenarios passing there. Its cleanup records the capacity the
release used and removes the change's namespace and images.
