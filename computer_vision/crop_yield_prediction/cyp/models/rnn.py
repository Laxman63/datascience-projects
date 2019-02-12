from torch import nn

import math
from pathlib import Path

from .base import ModelBase


class RNNModel(ModelBase):
    """
    A PyTorch replica of the RNN structured model from the original paper. Note that
    this class assumes feature_engineering was run with channels_first=True

    Parameters
    ----------
    in_channels: int, default=9
        Number of channels in the input data. Default taken from the number of bands in the
        MOD09A1 + the number of bands in the MYD11A2 datasets
    num_bins: int, default=32
        Number of bins in the histogram
    hidden_size: int, default=128
        The size of the hidden state. Default taken from the original repository
    num_rnn_layers: int, default=1
        Number of recurrent layers. Default taken from the original repository
    rnn_dropout: float, default=0.25
        Default taken from the original repository (note, this is 1 - keep_prob)
    dense_features: list, or None, default=None.
        output feature size of the Linear layers. If None, default values will be taken from the paper.
        The length of the list defines how many linear layers are used.
    savedir: pathlib Path, default=Path('data/models')
        The directory into which the models should be saved.
    """

    def __init__(self, in_channels=9, num_bins=32, hidden_size=128, num_rnn_layers=1, rnn_dropout=0.25,
                 dense_features=None, savedir=Path('data/models'), use_gp=True,
                 sigma=1, r_loc=0.5, r_year=1.5, sigma_e=0.01, sigma_b=0.01):

        model = RNNet(in_channels=in_channels, num_bins=num_bins, hidden_size=hidden_size,
                      num_rnn_layers=num_rnn_layers, rnn_dropout=rnn_dropout,
                      dense_features=dense_features)

        if dense_features is None:
            num_dense_layers = 2
        else:
            num_dense_layers = len(dense_features)
        model_weight = f'dense_layers.{num_dense_layers - 1}.weight'
        model_bias = f'dense_layers.{num_dense_layers - 1}.bias'

        super().__init__(model, model_weight, model_bias, 'rnn', savedir, use_gp, sigma, r_loc, r_year,
                         sigma_e, sigma_b)


class RNNet(nn.Module):
    """
    A crop yield conv net.

    For a description of the parameters, see the RNNModel class.
    """
    def __init__(self, in_channels=9, num_bins=32, hidden_size=128, num_rnn_layers=1,
                 rnn_dropout=0.25, dense_features=None):
        super().__init__()

        if dense_features is None:
            dense_features = [256, 1]
        dense_features.insert(0, hidden_size)

        self.rnn = nn.LSTM(input_size=in_channels * num_bins, hidden_size=hidden_size,
                           num_layers=num_rnn_layers, dropout=rnn_dropout, batch_first=True)
        self.hidden_size = hidden_size

        self.dense_layers = nn.ModuleList([
            nn.Linear(in_features=dense_features[i-1],
                      out_features=dense_features[i]) for i in range(1, len(dense_features))
        ])

        self.initialize_weights()

    def initialize_weights(self):

        sqrt_k = math.sqrt(1 / self.hidden_size)
        for parameters in self.rnn.all_weights:
            for pam in parameters:
                nn.init.uniform_(pam.data, -sqrt_k, sqrt_k)

        for dense_layer in self.dense_layers:
            nn.init.kaiming_uniform_(dense_layer.weight.data)
            nn.init.constant_(dense_layer.bias.data, 0)

    def forward(self, x, return_last_dense=False):
        """
        If return_last_dense is true, the feature vector generated by the second to last
        dense layer will also be returned. This is then used to train a Gaussian Process model.
        """
        # the model expects feature_engineer to have been run with channels_first=True, which means
        # the input is [batch, bands, times, bins].
        # Reshape to [batch, times, bands * bins]
        x = x.permute(0, 2, 1, 3).contiguous()
        x = x.view(x.shape[0], x.shape[1], x.shape[2] * x.shape[3])
        x, _ = self.rnn(x)
        x = x[:, -1, :]
        for layer_number, dense_layer in enumerate(self.dense_layers):
            x = dense_layer(x)
            if return_last_dense and (layer_number == len(self.dense_layers) - 2):
                output = x
        if return_last_dense:
            return x, output
        return x
