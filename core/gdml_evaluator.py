"""
GdmIEvaluator - GDML Expression Evaluator

GDML attribute values support mathematical expressions, e.g.:
  - "pi", "2.*pi", "pi/2."
  - "x+10", "9825-DOFFSET"
  - "PCOLL2_THICK/2+5"

This evaluator handles variable substitution and basic arithmetic.
"""

import math
from typing import Dict, Optional


class GdmIEvaluator:
    """
    GDML expression evaluator.

    Supports:
    - Predefined constants: pi, HALFPI, TWOPI
    - User-defined constant substitution
    - Basic arithmetic + negation
    """

    _PREDEFINED = {
        "pi": math.pi,
        "PI": math.pi,
        "HALFPI": math.pi / 2.0,
        "TWOPI": 2.0 * math.pi,
    }

    def __init__(self):
        self._constants: Dict[str, float] = {}
        self._constants.update(self._PREDEFINED)

    def set_constant(self, name: str, value: float):
        """Set a user-defined constant"""
        self._constants[name] = value

    def set_constants(self, const_dict: Dict[str, float]):
        """Set multiple constants at once"""
        self._constants.update(const_dict)

    def get_constant(self, name: str) -> Optional[float]:
        """Get a constant value by name"""
        return self._constants.get(name)

    def evaluate(self, expression: str) -> float:
        """
        Evaluate an expression.

        Args:
            expression: Math expression string, e.g. "2.*pi", "10+5*2", "PCOLL2_THICK/2+5"

        Returns:
            Evaluated float result

        Raises:
            ValueError: If expression cannot be evaluated
        """
        if not expression:
            return 0.0

        expr = expression.strip()
        if not expr:
            return 0.0

        # Try direct float conversion first
        try:
            return float(expr)
        except ValueError:
            pass

        # Replace all known constants (descending length to avoid partial substitution)
        for name in sorted(self._constants.keys(), key=len, reverse=True):
            if name in expr:
                expr = expr.replace(name, str(self._constants[name]))

        # Clean up: replace any remaining undefined letter tokens (from external refs) with 0
        import re
        # Match all identifiers starting with a letter or underscore
        for match in re.finditer(r'[A-Za-z_][A-Za-z0-9_]*', expr):
            token = match.group()
            # Skip pure numeric strings, math constant e, and unit characters
            if token in ('e',):
                continue
            try:
                float(token)
            except ValueError:
                expr = expr.replace(token, '0')
        allowed = set("0123456789.+-*/() ")
        cleaned = ""
        for ch in expr:
            if ch in allowed:
                cleaned += ch
            elif ch.isspace():
                cleaned += " "
            else:
                try:
                    return float(eval(expr, {"__builtins__": {}}, math.__dict__))
                except Exception:
                    raise ValueError(f"Cannot evaluate expression: '{expression}'")

        try:
            return float(eval(cleaned, {"__builtins__": {}}, math.__dict__))
        except Exception as e:
            raise ValueError(f"Cannot evaluate expression '{expression}': {e}")

    def clear(self):
        """Clear user-defined constants, keep predefined ones"""
        self._constants.clear()
        self._constants.update(self._PREDEFINED)
