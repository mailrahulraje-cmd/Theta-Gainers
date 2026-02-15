"""
Unified Phase Architecture - Single source of truth for system state.

Replaces scattered boolean flags with deterministic Enum-based phases.
Maintains backward compatibility with existing code.
"""

from enum import Enum, auto


class Phase(Enum):
    """
    System execution phase - single source of truth.
    
    Phases represent the complete lifecycle:
    INIT → ENTRY_ALLOWED → POSITION_OPEN → TRAILING_ACTIVE → HARD_EXIT → CLOSED
    
    DO NOT add new phases without updating phase_monitor().
    DO NOT skip phases (transitions are sequential and logged).
    """
    
    INIT = auto()              # System initializing, waiting for market open
    ENTRY_ALLOWED = auto()     # Market open, legs selected, ready for entry
    POSITION_OPEN = auto()     # One or more legs entered, actively trading
    TRAILING_ACTIVE = auto()   # Trailing stop-loss in effect (14:15+)
    HARD_EXIT = auto()         # Market close time reached, flattening all positions
    CLOSED = auto()            # All positions closed, end of day


class LegState(Enum):
    """
    Individual option leg lifecycle.
    Each of the 4 legs (SELL_CE, SELL_PE, BUY_CE, BUY_PE) tracks independently.
    """
    
    INIT = auto()              # Not yet evaluated
    READY = auto()             # Strike selected, waiting for entry signal
    ENTERED = auto()            # Position opened
    TRAILING = auto()           # Trailing SL active
    STOPPED_OUT = auto()        # Exited via stop-loss
    PROFIT_TAKEN = auto()       # Exited via take-profit
    CLOSED = auto()             # Closed (any reason)


class PhaseManager:
    """
    Unified phase management with deterministic transitions and logging.
    Replaces scattered boolean flags with single source of truth.
    """
    
    def __init__(self, logger):
        """
        Initialize phase manager.
        
        Args:
            logger: logging.Logger instance
        """
        self.logger = logger
        self._current_phase = Phase.INIT
        self._last_logged_phase = None  # Track to log transition only once
        self._transition_count = 0
        self._leg_states = {
            'sell_ce': LegState.INIT,
            'sell_pe': LegState.INIT,
            'buy_ce': LegState.INIT,
            'buy_pe': LegState.INIT,
        }
    
    def set_phase(self, new_phase: Phase, reason: str = "") -> bool:
        """
        Set new phase with logging.
        
        Args:
            new_phase: New Phase value
            reason: Optional reason for transition (logged)
            
        Returns:
            True if phase changed, False if already in phase
        """
        if not isinstance(new_phase, Phase):
            self.logger.error(f"[PHASE] Invalid phase type: {type(new_phase)}")
            return False
        
        # Log transition once
        if self._current_phase != new_phase:
            self._transition_count += 1
            self.logger.info(
                f"[PHASE {self._transition_count}] {self._current_phase.name} → {new_phase.name}"
                + (f" ({reason})" if reason else "")
            )
            self._current_phase = new_phase
            return True
        
        return False
    
    def get_phase(self) -> Phase:
        """Get current phase"""
        return self._current_phase
    
    def is_phase(self, phase: Phase) -> bool:
        """Check if current phase matches"""
        return self._current_phase == phase
    
    def is_before(self, phase: Phase) -> bool:
        """Check if current phase is before given phase"""
        return self._current_phase.value < phase.value
    
    def is_after(self, phase: Phase) -> bool:
        """Check if current phase is after given phase"""
        return self._current_phase.value > phase.value
    
    def set_leg_state(self, leg: str, state: LegState):
        """Set individual leg state"""
        if leg in self._leg_states:
            old_state = self._leg_states[leg]
            if old_state != state:
                self.logger.debug(f"[LEG] {leg.upper()}: {old_state.name} → {state.name}")
            self._leg_states[leg] = state
    
    def get_leg_state(self, leg: str) -> LegState:
        """Get individual leg state"""
        return self._leg_states.get(leg, LegState.INIT)
    
    def is_leg_entered(self, leg: str) -> bool:
        """Check if leg is entered"""
        state = self.get_leg_state(leg)
        return state in (LegState.ENTERED, LegState.TRAILING, LegState.STOPPED_OUT, LegState.PROFIT_TAKEN)
    
    def is_leg_open(self, leg: str) -> bool:
        """Check if leg has open position"""
        state = self.get_leg_state(leg)
        return state in (LegState.ENTERED, LegState.TRAILING)
    
    def get_state_dict(self) -> dict:
        """Export for state persistence"""
        return {
            'phase': self._current_phase.name,
            'transition_count': self._transition_count,
            'leg_states': {k: v.name for k, v in self._leg_states.items()},
        }
    
    def restore_from_dict(self, state_dict: dict):
        """Restore from persisted state"""
        try:
            phase_name = state_dict.get('phase', 'INIT')
            self._current_phase = Phase[phase_name]
            self._transition_count = state_dict.get('transition_count', 0)
            
            leg_states = state_dict.get('leg_states', {})
            for leg, state_name in leg_states.items():
                if leg in self._leg_states and state_name:
                    try:
                        self._leg_states[leg] = LegState[state_name]
                    except KeyError:
                        self.logger.warning(f"Unknown leg state: {state_name}")
            
            self.logger.info(f"[PHASE] Restored phase: {self._current_phase.name} (transitions: {self._transition_count})")
        except Exception as e:
            self.logger.warning(f"[PHASE] Failed to restore state: {e} (resetting to INIT)")
            self._current_phase = Phase.INIT
