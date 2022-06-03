from typing import Optional, Tuple, Union
import torch
from torch.nn import Module
from hatespace.models.base import Embedder
from transformers import EncoderDecoderModel
from transformers.modeling_outputs import Seq2SeqLMOutput
from hatespace.models.nlp.modeling_outputs import ArchetypalTransformerModelOutput
from transformers.modeling_outputs import BaseModelOutputWithPoolingAndCrossAttentions

from transformers import logging

logging.set_verbosity_error()

def shift_tokens_right(self, input_ids: torch.Tensor, pad_token_id: int, decoder_start_token_id: int):
    """
    Shift input ids one token to the right.
    """
    shifted_input_ids = input_ids.new_zeros(input_ids.shape)
    shifted_input_ids[:, 1:] = input_ids[:, :-1].clone()
    if decoder_start_token_id is None:
        raise ValueError("Make sure to set the decoder_start_token_id attribute of the model's configuration.")
    shifted_input_ids[:, 0] = decoder_start_token_id

    if pad_token_id is None:
        raise ValueError("Make sure to set the pad_token_id attribute of the model's configuration.")
    # replace possible -100 values in labels by `pad_token_id`
    shifted_input_ids.masked_fill_(shifted_input_ids == -100, pad_token_id)

    return shifted_input_ids

# TODO This guy needs a better name
class TransformerArchetypal(EncoderDecoderModel):
    def __init__(
        self, model_name_or_path: Union[str, Tuple[str]], inner_embedder: Embedder
    ) -> None:
        if isinstance(model_name_or_path, (tuple, list)):
            encoder_type, decoder_type = model_name_or_path
        else:
            encoder_type = model_name_or_path
            decoder_type = model_name_or_path
        encoder_decoder = EncoderDecoderModel.from_encoder_decoder_pretrained(
            encoder_type, decoder_type
        )

        super().__init__(
            config=encoder_decoder.config,
            encoder=encoder_decoder.encoder,
            decoder=encoder_decoder.decoder,
        )
        del encoder_decoder

        self.train()
        self.gradient_checkpointing_disable()

        self.inner_embedder = inner_embedder
        self.vocab_size = self.decoder.config.vocab_size

    def forward(
        self,
        input_ids: Optional[torch.LongTensor] = None,
        attention_mask: Optional[torch.FloatTensor] = None,
        decoder_input_ids: Optional[torch.LongTensor] = None,
        decoder_attention_mask: Optional[torch.BoolTensor] = None,
        encoder_outputs: Optional[Tuple[torch.FloatTensor]] = None,
        past_key_values: Tuple[Tuple[torch.FloatTensor]] = None,
        inputs_embeds: Optional[torch.FloatTensor] = None,
        decoder_inputs_embeds: Optional[torch.FloatTensor] = None,
        labels: Optional[torch.LongTensor] = None,
        use_cache: Optional[bool] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = None,
        return_dict: Optional[bool] = None,
        **kwargs,
    ):
        return_dict = (
            return_dict
            if return_dict is not None
            else self.encoder.config.use_return_dict
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

        if encoder_outputs is None:
          encoder_outputs = self.encoder(
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

        if decoder_input_ids is None:
          decoder_input_ids = shift_tokens_right(
              input_ids, self.config.pad_token_id, self.config.decoder_start_token_id
          )

        decoder_outputs = self.decoder(
            input_ids=decoder_input_ids,
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

        return ArchetypalTransformerModelOutput(
            logits=decoder_outputs.logits,
            embeddings=embeddings,
            past_key_values=decoder_outputs.past_key_values,
            decoder_hidden_states=decoder_outputs.hidden_states,
            decoder_attentions=decoder_outputs.attentions,
            cross_attentions=decoder_outputs.cross_attentions,
            encoder_last_hidden_state=encoder_outputs.last_hidden_state,
            encoder_hidden_states=encoder_outputs.hidden_states,
            encoder_attentions=encoder_outputs.attentions,
        )

    def generate_from_sequence(
        self, inputs: torch.Tensor, *args, **kwargs
    ) -> torch.LongTensor:
        return self.generate(inputs=inputs, *args, **kwargs)

    def generate_from_embeddings(
        self, embeddings: torch.Tensor, *args, **kwargs
    ) -> torch.LongTensor:
        intermediate_encodings = self.inner_embedder.decoder(embeddings)
        intermediate_encodings = torch.reshape(intermediate_encodings, (embeddings.shape[0], 512, 768))
        intermediate_encodings = BaseModelOutputWithPoolingAndCrossAttentions(last_hidden_state=intermediate_encodings)
        return self.generate(
            inputs=None, encoder_outputs=intermediate_encodings, *args, **kwargs
        )


class LinearArchetypal(Embedder):
    def __init__(self, input_dimensions, num_archetypes) -> None:
        encoder = torch.nn.Sequential(
            torch.nn.Linear(input_dimensions, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, num_archetypes),
            torch.nn.Softmax(dim=1),
        )
        decoder = torch.nn.Sequential(
            torch.nn.Linear(num_archetypes, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, input_dimensions),
            torch.nn.ReLU(),
        )
        super().__init__(encoder=encoder, decoder=decoder)

    def forward(self, x):
        input_shape = x.shape
        x = torch.flatten(x, start_dim=1)
        embedding = self.encoder(x)
        output = torch.reshape(self.decoder(embedding), input_shape)
        return (output, embedding)
