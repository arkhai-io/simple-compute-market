# Shell functions deciding which of a host's GPUs a create may pass through.
# Every task of the create that selects, counts, or lists GPUs for passthrough
# includes this file verbatim, so all of them apply one test.
#
# A candidate is a GPU the host's capability inventory lists as available for
# passthrough. It is eligible unless a defined guest already has it attached,
# or it is the host's boot GPU, the device the host's console runs on. The boot
# GPU is eligible only when the pool's operator opts in
# (vm_passthrough_boot_gpu) and the kernel reports it bound to vfio-pci now:
# the inventory is a file written earlier, and can still list a GPU an operator
# has since returned to its host driver, so it is never taken alone. Nothing
# here binds or unbinds a device.
#
# Whether a candidate is the boot GPU is read from that device's own sysfs
# boot_vga flag. It is not parsed from `lspci -vmm`, whose field order
# (Slot: before Class:) a parse would have to assume.

# The kernel's view of every PCI device, one directory per address.
PCI_DEVICES=/sys/bus/pci/devices

# Whether ADDRESS is the host's boot GPU, by its own boot_vga flag.
gpu_is_boot_gpu() {
  [ "$(cat "$PCI_DEVICES/$1/boot_vga" 2>/dev/null)" = "1" ]
}

# The driver the kernel has bound ADDRESS to now; empty when none is.
gpu_driver() {
  local link
  link="$(readlink "$PCI_DEVICES/$1/driver" 2>/dev/null || true)"
  printf '%s' "${link##*/}"
}

# Every host PCI address a defined guest has attached, one per line, as the
# inventory writes them (0000:01:00.0). Only a hostdev's source address is
# read, never the address the device has inside the guest. Fails when the
# defined guests cannot be read, since attachment is then unknown.
gpus_attached_to_guests() {
  local names guest xml address domain bus slot fn
  names="$(virsh list --all --name)" || return 1
  for guest in $names; do
    xml="$(virsh dumpxml "$guest")" || return 1
    while IFS= read -r address; do
      [ -n "$address" ] || continue
      domain="${address#*domain=\'}"; domain="${domain%%\'*}"
      bus="${address#*bus=\'}"; bus="${bus%%\'*}"
      slot="${address#*slot=\'}"; slot="${slot%%\'*}"
      fn="${address#*function=\'}"; fn="${fn%%\'*}"
      # libvirt writes each part as hex with a 0x prefix; one without it is
      # read as hex all the same, never as octal.
      printf '%04x:%02x:%02x.%x\n' "0x${domain#0x}" "0x${bus#0x}" "0x${slot#0x}" "0x${fn#0x}"
    done <<< "$(awk '
      /<hostdev / && /type=.pci./ { hostdev = 1 }
      hostdev && /<source>/ { source = 1 }
      source && /<address / { print; source = 0 }
      /<\/hostdev>/ { hostdev = 0; source = 0 }
    ' <<< "$xml")"
  done
  return 0
}

# Why ADDRESS may not be passed through, given whether the pool opts in to the
# boot GPU (OPT_IN, `true` or `false`) and the space-padded list of ATTACHED
# addresses; prints nothing when it may.
gpu_ineligibility() {
  local address="$1" opt_in="$2" attached="$3" driver
  case "$attached" in
    *" $address "*)
      printf 'attached to a defined guest'
      return 0
      ;;
  esac
  if gpu_is_boot_gpu "$address"; then
    if [ "$opt_in" != "true" ]; then
      printf 'the boot GPU, and the pool does not opt in to passing it through'
      return 0
    fi
    driver="$(gpu_driver "$address")"
    if [ "$driver" != "vfio-pci" ]; then
      printf 'the boot GPU, bound to %s rather than vfio-pci' "${driver:-no driver}"
      return 0
    fi
  fi
  return 0
}

# The CANDIDATES (whitespace-separated inventory addresses) that may be passed
# through, one per line, in the inventory's order; each one left out is named,
# with why, on stderr. Fails when attachment cannot be read.
eligible_gpus() {
  local candidates="$1" opt_in="$2" attached address reason
  attached="$(gpus_attached_to_guests)" || return 1
  attached=" $(printf '%s' "$attached" | tr '\n' ' ') "
  for address in $candidates; do
    reason="$(gpu_ineligibility "$address" "$opt_in" "$attached")"
    if [ -n "$reason" ]; then
      echo "Not eligible: $address, $reason" >&2
    else
      printf '%s\n' "$address"
    fi
  done
  return 0
}
