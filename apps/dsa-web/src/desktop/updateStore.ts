import type { DesktopUpdateState } from './runtime';

type SharedDesktopUpdateListener = () => void;

let sharedState: DesktopUpdateState | null = null;
let checkInFlight = false;
const listeners = new Set<SharedDesktopUpdateListener>();

export function getSharedDesktopUpdateState() {
  return sharedState;
}

export function isDesktopUpdateCheckInFlight() {
  return checkInFlight;
}

export function beginDesktopUpdateCheck() {
  if (checkInFlight) {
    return false;
  }
  checkInFlight = true;
  return true;
}

export function endDesktopUpdateCheck() {
  checkInFlight = false;
}

export function setSharedDesktopUpdateState(nextState: DesktopUpdateState | null) {
  sharedState = nextState;
  listeners.forEach((listener) => listener());
}

export function subscribeSharedDesktopUpdateState(listener: SharedDesktopUpdateListener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function resetSharedDesktopUpdateState() {
  sharedState = null;
  checkInFlight = false;
  listeners.forEach((listener) => listener());
}
