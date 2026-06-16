"""Lightweight ADS-B detector and decoder helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Union


def _normalize_hex(value: Union[str, bytes, bytearray]) -> str:
	if isinstance(value, (bytes, bytearray)):
		value = value.hex()
	value = value.strip().replace(" ", "").replace(",", "")
	if value.startswith(("0x", "0X")):
		value = value[2:]
	return value.upper()


def is_adsb_message(value: Union[str, bytes, bytearray]) -> bool:
	"""Return True if the payload looks like an ADS-B extended squitter."""
	try:
		msg = _normalize_hex(value)
		raw = bytes.fromhex(msg)
	except (ValueError, TypeError):
		return False

	if len(raw) not in (7, 14):
		return False

	df = raw[0] >> 3
	if df != 17:
		return False

	type_code = (raw[4] >> 3) & 0x1F
	return 1 <= type_code <= 31


def adsb_type_code(value: Union[str, bytes, bytearray]) -> Optional[int]:
	"""Extract the ADS-B type code if present."""
	if not is_adsb_message(value):
		return None
	raw = bytes.fromhex(_normalize_hex(value))
	return (raw[4] >> 3) & 0x1F


def message_kind(value: Union[str, bytes, bytearray]) -> str:
	"""Return a human-friendly message class."""
	tc = adsb_type_code(value)
	if tc is None:
		return "not_adsb"
	if 1 <= tc <= 4:
		return "aircraft_id"
	if 5 <= tc <= 8:
		return "surface_position"
	if 9 <= tc <= 18:
		return "airborne_position"
	if tc == 19:
		return "velocity"
	if 20 <= tc <= 22:
		return "airborne_position"
	if 23 <= tc <= 27:
		return "reserved"
	if 28 <= tc <= 31:
		return "status"
	return "unknown"


@dataclass
class ADSBDetector:
	"""Tiny stateful detector for incoming messages."""

	total: int = 0
	adsb: int = 0
	last_message: Optional[str] = None
	last_type_code: Optional[int] = None
	history: list[str] = field(default_factory=list)

	def feed(self, value: Union[str, bytes, bytearray]) -> bool:
		self.total += 1
		msg = _normalize_hex(value)
		self.last_message = msg
		self.last_type_code = adsb_type_code(msg)
		detected = self.last_type_code is not None
		if detected:
			self.adsb += 1
			self.history.append(msg)
			self.history = self.history[-20:]
		return detected

	def stats(self) -> dict:
		return {
			"total": self.total,
			"adsb": self.adsb,
			"rate": (self.adsb / self.total) if self.total else 0.0,
			"last_type_code": self.last_type_code,
		}


def detect_stream(messages: Iterable[Union[str, bytes, bytearray]]) -> list[bool]:
	"""Detect ADS-B messages in an iterable of payloads."""
	detector = ADSBDetector()
	return [detector.feed(message) for message in messages]


if __name__ == "__main__":
	import sys

	detector = ADSBDetector()
	for arg in sys.argv[1:]:
		ok = detector.feed(arg)
		print(f"{arg}: {'ADS-B' if ok else 'not ADS-B'} ({message_kind(arg)})")
	if len(sys.argv) > 1:
		print(detector.stats())
