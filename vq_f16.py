import torch
import torch.nn as nn
from vq_modules import Encoder, Decoder
from vq_modules import VectorQuantizer2 as VectorQuantizer
from codebook import Codebook

class VQModel(nn.Module):
    def __init__(self, device, ckpt_path=None):
        super().__init__()
        ddconfig = {'double_z': False, 'z_channels': 256, 'resolution': 256, 'in_channels': 3, 'out_ch': 3, 'ch': 128, 'ch_mult': [1, 1, 2, 2, 4], 'num_res_blocks': 2, 'attn_resolutions': [16], 'dropout': 0.0}
        embed_dim = 256
        n_embed = 1024
        self.encoder = Encoder(**ddconfig).to(device=device)
        self.decoder = Decoder(**ddconfig).to(device=device)
        self.quantize = VectorQuantizer(n_embed, embed_dim, beta=0.25).to(device=device)
        self.quant_conv = torch.nn.Conv2d(ddconfig["z_channels"], embed_dim, 1).to(device=device)
        self.post_quant_conv = torch.nn.Conv2d(embed_dim, ddconfig["z_channels"], 1).to(device=device)
        # if ckpt_path is not None:
        #     self.init_from_ckpt(ckpt_path)

    def init_from_ckpt(self, path):
        sd = torch.load(path, map_location="cpu")
        self.load_state_dict(sd, strict=False)
        print(f"Restored from {path}")

    def encode(self, x):
        h = self.encoder(x)
        h = self.quant_conv(h)
        quant, emb_loss, info = self.quantize(h)
        return quant, emb_loss, info

    def decode(self, quant):
        quant = self.post_quant_conv(quant)
        dec = self.decoder(quant)
        return dec

    def decode_code(self, code_b):
        quant_b = self.quantize.embed_code(code_b)
        dec = self.decode(quant_b)
        return dec

    def forward(self, input):
        quant, diff, _ = self.encode(input)
        dec = self.decode(quant)
        return dec, diff
    
    # lambda factor to weight the VQ_VAE loss and GAN loss (see the paper)
    def calculate_lambda(self, nll_loss, gan_loss):
        #nll_loss = perceptual reconstruction loss
        #gan_loss = gan_loss

        #its calculate on last layers
        last_layer = self.decoder.model[-1]
        last_layer_weight = last_layer.weight

        # torch.autograd.grad calculate the gradient, retain_graph means we want to keep the curren
        # computational graph which is just important that the backward pass can function properly
        nll_grads = torch.autograd.grad(nll_loss, last_layer_weight, retain_graph=True)[0] 
        g_grads = torch.autograd.grad(gan_loss, last_layer_weight, retain_graph=True)[0]

        # λ is a ratio
        λ = torch.norm(nll_grads) / (torch.norm(g_grads) + 1e-4)
        λ = torch.clamp(λ, 0, 1e4).detach() # clipping the values to be between 0 and 10k
        return 0.8 * λ
    
    @staticmethod
    def adopt_weight(disc_factor, i, threshold, value=0.):
        if i < threshold:
            disc_factor = value
        return disc_factor


# RuDalle image pos embeddings

def get_image_pos_embeddings(self, image_input_ids, past_length=0):
    input_shape = image_input_ids.size()
    row_ids = torch.arange(past_length, input_shape[-1] + past_length,
                           dtype=torch.long, device=self.device) // self.image_tokens_per_dim
    row_ids = row_ids.unsqueeze(0).view(-1, input_shape[-1])
    col_ids = torch.arange(past_length, input_shape[-1] + past_length,
                           dtype=torch.long, device=self.device) % self.image_tokens_per_dim
    col_ids = col_ids.unsqueeze(0).view(-1, input_shape[-1])
    return self.image_row_embeddings(row_ids) + self.image_col_embeddings(col_ids)