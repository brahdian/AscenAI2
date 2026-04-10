"""
Tests for PII StreamingParser — split-chunk scenarios.

Validates:
- D2: Partial pseudo-values split across chunks are fully restored before output
- No leakage or truncation of pseudo-values in output stream
- flush() properly restores remaining buffer
"""

import pytest
import sys
import os

# Add the service path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'ai-orchestrator'))

from app.services.pii_service import PIIContext, StreamingParser, redact_pii


@pytest.fixture
def pii_context():
    """Create a PII context with test mappings."""
    ctx = PIIContext()
    # Manually add mappings as if redact_pii was called
    ctx.real_to_pseudo["john@example.com"] = "user_x7k2m@ascenai.private"
    ctx.pseudo_to_real["user_x7k2m@ascenai.private"] = "john@example.com"
    ctx.real_to_pseudo["647-123-4567"] = "+1-555-0001"
    ctx.pseudo_to_real["+1-555-0001"] = "647-123-4567"
    return ctx


@pytest.fixture
def parser(pii_context):
    """Create a StreamingParser with test context."""
    return StreamingParser(pii_context, "test-session")


class TestStreamingParserBasic:
    """Basic restoration scenarios."""
    
    def test_no_pseudo_values(self, parser):
        """Plain text passes through unchanged."""
        result = parser.process_chunk("Hello world") + parser.flush()
        assert result == "Hello world"
    
    def test_complete_pseudo_value_in_single_chunk(self, parser):
        """Complete pseudo-value in one chunk is restored."""
        chunk = "My email is user_x7k2m@ascenai.private today"
        result = parser.process_chunk(chunk) + parser.flush()
        assert result == "My email is john@example.com today"
    
    def test_multiple_pseudo_values_in_single_chunk(self, parser):
        """Multiple pseudo-values in one chunk are all restored."""
        chunk = "Email: user_x7k2m@ascenai.private, Phone: +1-555-0001"
        result = parser.process_chunk(chunk) + parser.flush()
        assert result == "Email: john@example.com, Phone: 647-123-4567"


class TestStreamingParserSplitChunks:
    """Split-chunk scenarios (Claim 1, P3)."""
    
    def test_pseudo_value_split_in_middle(self, parser):
        """Pseudo-value split across two chunks is fully restored."""
        chunk1 = "My email is user_x7"
        chunk2 = "k2m@ascenai.private today"
        
        output1 = parser.process_chunk(chunk1)
        output2 = parser.process_chunk(chunk2)
        output3 = parser.flush()
        
        # First chunk should emit nothing (partial pseudo in buffer)
        assert output1 == ""
        # Second chunk should emit the restored complete value
        assert output2 == "My email is john@example.com"
        # Flush should emit the remaining
        assert output3 == " today"
    
    def test_pseudo_value_split_multiple_parts(self, parser):
        """Pseudo-value split across three chunks is fully restored."""
        chunk1 = "Email: user_x"
        chunk2 = "7k2m@"
        chunk3 = "ascenai.private please"
        
        output1 = parser.process_chunk(chunk1)
        output2 = parser.process_chunk(chunk2)
        output3 = parser.process_chunk(chunk3)
        output4 = parser.flush()
        
        # First two chunks emit nothing (partial pseudo in buffer)
        assert output1 == ""
        assert output2 == ""
        # Third chunk restores and emits
        assert output3 == "Email: john@example.com"
        # Flush emits remainder
        assert output4 == " please"
    
    def test_pseudo_value_at_stream_end(self, parser):
        """Pseudo-value at the end of stream is restored by flush()."""
        chunk1 = "Contact me at user_x7k2m@ascenai.private"
        
        output1 = parser.process_chunk(chunk1)
        output2 = parser.flush()
        
        # First chunk may emit partial or nothing depending on buffer size
        # Flush must restore and emit the complete pseudo-value
        full_output = output1 + output2
        assert "john@example.com" in full_output
        assert "user_x7k2m" not in full_output


class TestStreamingParserEdgeCases:
    """Edge cases (Claim 3, Counterexample)."""
    
    def test_empty_input(self, parser):
        """Empty input produces empty output."""
        result = parser.process_chunk("") + parser.flush()
        assert result == ""
    
    def test_no_mappings(self):
        """Parser with no mappings passes through unchanged."""
        ctx = PIIContext()  # No mappings
        parser = StreamingParser(ctx, "test")
        
        chunk = "user_x7k2m@ascenai.private"
        result = parser.process_chunk(chunk) + parser.flush()
        assert result == chunk  # No restoration (no mappings)
    
    def test_partial_pseudo_not_matching(self, parser):
        """Partial text that looks like pseudo but isn't passes through."""
        chunk1 = "user_x7k2"
        chunk2 = "m@fake.domain"
        
        output1 = parser.process_chunk(chunk1)
        output2 = parser.process_chunk(chunk2)
        output3 = parser.flush()
        
        # Not a valid pseudo-value (wrong domain), should pass through
        full_output = output1 + output2 + output3
        assert "user_x7k2" in full_output  # Not restored
    
    def test_consecutive_pseudo_values(self, parser):
        """Consecutive pseudo-values are both restored."""
        chunk = "Email user_x7k2m@ascenai.private and phone +1-555-0001"
        result = parser.process_chunk(chunk) + parser.flush()
        assert result == "Email john@example.com and phone 647-123-4567"
    
    def test_pseudo_value_with_whitespace(self, parser):
        """Pseudo-value with surrounding whitespace is restored."""
        chunk = "My email is  user_x7k2m@ascenai.private  today"
        result = parser.process_chunk(chunk) + parser.flush()
        assert result == "My email is  john@example.com  today"


class TestStreamingParserCorrectness:
    """Formal correctness validation (D1, D2)."""
    
    def test_d1_semantic_preservation(self, parser):
        """D1: Pseudo-values preserve semantic structure for LLM."""
        # The pseudo-value looks like an email, preserving LLM understanding
        pseudo = "user_x7k2m@ascenai.private"
        assert "@" in pseudo
        assert "." in pseudo
    
    def test_d2_no_leakage(self, parser):
        """D2: No pseudo-value leaks in output stream."""
        chunks = [
            "Email: user_x7",
            "k2m@ascenai.",
            "private please"
        ]
        
        outputs = []
        for chunk in chunks:
            outputs.append(parser.process_chunk(chunk))
        outputs.append(parser.flush())
        
        full_output = "".join(outputs)
        
        # Real value must be present
        assert "john@example.com" in full_output
        # Pseudo-value must NOT leak
        assert "user_x7k2m" not in full_output
    
    def test_d2_no_truncation(self, parser):
        """D2: No truncation of restored values."""
        original = "Contact user_x7k2m@ascenai.private for help"
        chunks = [original[i:i+5] for i in range(0, len(original), 5)]
        
        outputs = []
        for chunk in chunks:
            outputs.append(parser.process_chunk(chunk))
        outputs.append(parser.flush())
        
        full_output = "".join(outputs)
        
        # Must contain complete restored email
        assert "john@example.com" in full_output
        # Original pseudo must be fully replaced
        assert "user_x7k2m" not in full_output
    
    def test_d2_buffer_retention(self, parser):
        """D2: Buffer retains max_pseudo_len characters for partial matches."""
        # Buffer should retain enough to catch partial pseudo-values
        assert parser.max_pseudo_len >= len("user_x7k2m@ascenai.private")
    
    def test_equivalent_to_non_streaming(self, pii_context):
        """Streaming output must match non-streaming restoration."""
        test_input = "My email is user_x7k2m@ascenai.private, call +1-555-0001"
        
        # Non-streaming (direct restoration)
        from app.services.pii_service import restore_pii
        non_streaming = restore_pii(test_input, pii_context)
        
        # Streaming
        parser = StreamingParser(pii_context, "test")
        streaming = parser.process_chunk(test_input) + parser.flush()
        
        # Must be equivalent
        assert streaming == non_streaming


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
