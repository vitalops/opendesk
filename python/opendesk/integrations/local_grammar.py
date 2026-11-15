"""Schema-constrained MLX decoding; the dispatcher still validates every call."""
import json


class JSONConstraint:
    def __init__(self, tokenizer, schema):
        import llguidance
        from llguidance.numpy import allocate_token_bitmask
        self.matcher = llguidance.LLMatcher(tokenizer, llguidance.grammar_from('json_schema', json.dumps(schema)))
        self.mask = allocate_token_bitmask(1, tokenizer.vocab_size)
        self.first = True

    def __call__(self, tokens, logits):
        from llguidance.numpy import fill_next_token_bitmask
        from llguidance.mlx import apply_token_bitmask
        if not self.first:
            self.matcher.consume_token(int(tokens.reshape(-1)[-1].item()))
            error = self.matcher.get_error()
            if error:
                raise ValueError(f'Constrained decoding failed: {error}')
        self.first = False
        fill_next_token_bitmask(self.matcher, self.mask, 0)
        masked = apply_token_bitmask(logits, self.mask)
        return masked.reshape(logits.shape)
