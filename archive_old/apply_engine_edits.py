from pathlib import Path
p = Path("strategy/engine.py")
text = p.read_text(encoding="utf-8")

# --- Insert imports after the contract import line ---
import_marker = "from contract import StateProtocol, FeedProtocol, BrokerProtocol, NotifierProtocol"
imports_to_add = (
    "from core.trade_leg_manager import TradeLegManager\n"
    "from contract import TradeLegV1\n"
    "from core.state_schema import validate_state_schema\n"
)
if import_marker in text and imports_to_add not in text:
    text = text.replace(import_marker, import_marker + "\n" + imports_to_add)

# --- Insert instantiation after SafetyValidator initialization ---
init_marker = "self.safety_validator = SafetyValidator(logger_instance=logger)"
instantiation = (
    "\n        # TradeLegManager for type-safe leg storage used by engine logic\n"
    "        self.trade_leg_manager = TradeLegManager()\n"
)
if init_marker in text and "self.trade_leg_manager = TradeLegManager()" not in text:
    text = text.replace(init_marker, init_marker + instantiation)

# Write back only if changed
p.write_text(text, encoding="utf-8")
print("EDIT_APPLIED" if import_marker in text and init_marker in text else "EDIT_MAY_NOT_HAVE_BEEN_APPLIED")
