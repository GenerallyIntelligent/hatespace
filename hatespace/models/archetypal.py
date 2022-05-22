from typing import Optional, Tuple
import torch
from torch.nn import Module
from hatespace.models.base import Embedder
from hatespace.models.nlp import TransformerEmbedder

# TODO This guy needs a better name
class TransformerArchetypal(Module):
    def __init__(
        self, transformers: TransformerEmbedder, inner_embedder: Embedder
    ) -> None:
        super().__init__()
        self.transformers = transformers
        self.inner_embedder = inner_embedder

    def forward(
        self,
        input_ids: Optional[torch.LongTensor] = None,
        attention_mask: Optional[torch.FloatTensor] = None,
        decoder_attention_mask: Optional[torch.BoolTensor] = None,
        past_key_values: Tuple[Tuple[torch.FloatTensor]] = None,
        inputs_embeds: Optional[torch.FloatTensor] = None,
        decoder_inputs_embeds: Optional[torch.FloatTensor] = None,
        use_cache: Optional[bool] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = None,
        return_dict: Optional[bool] = None,
        **kwargs,
    ):
        return_dict = (
            return_dict
            if return_dict is not None
            else self.transformers.encoder.config.use_return_dict
        )

        kwargs_encoder = {
            argument: value
            for argument, value in kwargs.items()
            if not argument.startswith("decoder_")
        }

        kwargs_decoder = {
            argument[len("decoder_") :]: value
            for argument, value in kwargs.items()
            if argument.startswith("decoder_")
        }

        encoder_outputs = self.transformers.encoder(
            input_ids=input_ids,
            attention_mask=attention_mask,
            inputs_embeds=inputs_embeds,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
            **kwargs_encoder,
        )

        predicted_encoder_hidden_states, embeddings = self.inner_embedder(
            encoder_outputs[0]
        )

        decoder_outputs = self.transformers.decoder(
            input_ids=input_ids,
            attention_mask=decoder_attention_mask,
            encoder_hidden_states=predicted_encoder_hidden_states,
            encoder_attention_mask=attention_mask,
            inputs_embeds=decoder_inputs_embeds,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            use_cache=use_cache,
            past_key_values=past_key_values,
            return_dict=return_dict,
            **kwargs_decoder,
        )

        return (decoder_outputs.logits, embeddings)


class LinearArchetypal(Embedder):
    def __init__(self, input_dimensions, num_archetypes) -> None:
        encoder = torch.nn.Sequential(
            torch.nn.Linear(input_dimensions, 128),
            torch.nn.ReLU(),
            torch.nn.Linear(128, num_archetypes),
            torch.nn.Softmax(dim=1),
        )
        decoder = torch.nn.Sequential(
            torch.nn.Linear(num_archetypes, 128),
            torch.nn.ReLU(),
            torch.nn.Linear(128, input_dimensions),
            torch.nn.ReLU(),
        )
        super().__init__(encoder=encoder, decoder=decoder)

    def forward(self, x):
        input_shape = x.shape
        x = torch.flatten(x, start_dim=1)
        embedding = self.encoder(x)
        output = torch.reshape(self.decoder(embedding), input_shape)
        return (output, embedding)
