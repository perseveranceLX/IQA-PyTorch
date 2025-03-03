from typing import Tuple
import numpy as np
import math
import torch
from torch import Tensor
import torch.nn as nn
import torch.nn.functional as F

from pyiqa.utils.matlab_functions import fspecial_gauss
from .arch_util import SimpleSamePadding2d, SymmetricPad2d

EPS = torch.finfo(torch.float32).eps

def extract_2d_patches(x, kernel, stride=1, dilation=1):
    """
    Ref: https://stackoverflow.com/a/65886666
    """
    # Do TF 'SAME' Padding
    b,c,h,w = x.shape
    h2 = math.ceil(h / stride)
    w2 = math.ceil(w / stride)
    pad_row = (h2 - 1) * stride + (kernel - 1) * dilation + 1 - h
    pad_col = (w2 - 1) * stride + (kernel - 1) * dilation + 1 - w
    x = F.pad(x, (pad_col//2, pad_col - pad_col//2, pad_row//2, pad_row - pad_row//2))
    
    # Extract patches
    patches = F.unfold(x, kernel, dilation, stride=stride)
    b, _, pnum = patches.shape
    patches = patches.transpose(1, 2).reshape(b, pnum, c, kernel, kernel)
    return patches


def nanmean(v, *args, inplace=False, **kwargs):
    if not inplace:
        v = v.clone()
    is_nan = torch.isnan(v)
    v[is_nan] = 0
    return v.sum(*args, **kwargs) / (~is_nan).float().sum(*args, **kwargs)


def torch_cov(tensor, rowvar=True, bias=False):
    r"""Estimate a covariance matrix (np.cov)
    Ref: https://gist.github.com/ModarTensai/5ab449acba9df1a26c12060240773110
    """
    tensor = tensor if rowvar else tensor.transpose(-1, -2)
    tensor = tensor - tensor.mean(dim=-1, keepdim=True)
    factor = 1 / (tensor.shape[-1] - int(not bool(bias)))
    return factor * tensor @ tensor.transpose(-1, -2)


def safe_sqrt(x: torch.Tensor) -> torch.Tensor:
    r"""Safe sqrt with EPS to ensure numeric stability.

    Args:
        x (torch.Tensor): should be non-negative 
    """
    EPS = torch.finfo(x.dtype).eps
    return torch.sqrt(x + EPS)


def imfilter(input, weight, bias=None, stride=1, padding='same', dilation=1, groups=1):
    """imfilter same as matlab.
    """
    kernel_size = weight.shape[-1]
    if padding.lower() == 'same':
        pad_func = SimpleSamePadding2d(kernel_size, stride=1, mode='constant')
    elif padding.lower() == 'replicate':
        pad_func = SimpleSamePadding2d(kernel_size, stride=1, mode='replicate')
    elif padding.lower() == 'symmetric':
        pad_func = SymmetricPad2d(kernel_size//2)
    
    return F.conv2d(
        pad_func(input), weight, bias, stride, dilation=dilation, groups=groups)


def normalize_img_with_guass(img: torch.Tensor, 
                             kernel_size: int = 7, 
                             sigma: float = 7. / 6, 
                             C: int = 1,
                             padding: str = 'same'):

    if padding.lower() == 'same':
        pad_func = SimpleSamePadding2d(kernel_size, stride=1)
    elif padding.lower() == 'replicate':
        pad_func = SimpleSamePadding2d(kernel_size, stride=1, mode='replicate')
        # pad_func = nn.ReplicationPad2d(kernel_size//2)
    elif padding.lower() == 'symmetric':
        pad_func = SymmetricPad2d(kernel_size//2)

    kernel = fspecial_gauss(kernel_size, sigma, 1).to(img)
    mu = F.conv2d(pad_func(img), kernel, groups=1)
    std = F.conv2d(pad_func(img**2), kernel, groups=1)
    sigma = safe_sqrt((std - mu**2).abs())
    img_normalized = (img - mu) / (sigma + C)
    return img_normalized


# Gradient operator kernels
def scharr_filter() -> torch.Tensor:
    r"""Utility function that returns a normalized 3x3 Scharr kernel in X direction
    Returns:
        kernel: Tensor with shape (1, 3, 3)
    """
    return torch.tensor([[[-3., 0., 3.], [-10., 0., 10.], [-3., 0., 3.]]]) / 16


def gradient_map(x: torch.Tensor, kernels: torch.Tensor) -> torch.Tensor:
    r""" Compute gradient map for a given tensor and stack of kernels.
    Args:
        x: Tensor with shape (N, C, H, W).
        kernels: Stack of tensors for gradient computation with shape (k_N, k_H, k_W)
    Returns:
        Gradients of x per-channel with shape (N, C, H, W)
    """
    padding = kernels.size(-1) // 2
    grads = torch.nn.functional.conv2d(x, kernels.to(x), padding=padding)
    return safe_sqrt(torch.sum(grads**2, dim=-3, keepdim=True))


def similarity_map(map_x: torch.Tensor,
                   map_y: torch.Tensor,
                   constant: float,
                   alpha: float = 0.0) -> torch.Tensor:
    r""" Compute similarity_map between two tensors using Dice-like equation.
    Args:
        map_x: Tensor with map to be compared
        map_y: Tensor with map to be compared
        constant: Used for numerical stability
        alpha: Masking coefficient. Substracts - `alpha` * map_x * map_y from denominator and nominator
    """
    return (2.0 * map_x * map_y - alpha * map_x * map_y + constant) / \
           (map_x ** 2 + map_y ** 2 - alpha * map_x * map_y + constant + EPS)


def ifftshift(x: torch.Tensor) -> torch.Tensor:
    r""" Similar to np.fft.ifftshift but applies to PyTorch Tensors"""
    shift = [-(ax // 2) for ax in x.size()]
    return torch.roll(x, shift, tuple(range(len(shift))))


def get_meshgrid(size: Tuple[int, int]) -> torch.Tensor:
    r"""Return coordinate grid matrices centered at zero point.
    Args:
        size: Shape of meshgrid to create
    """
    if size[0] % 2:
        # Odd
        x = torch.arange(-(size[0] - 1) / 2, size[0] / 2) / (size[0] - 1)
    else:
        # Even
        x = torch.arange(-size[0] / 2, size[0] / 2) / size[0]

    if size[1] % 2:
        # Odd
        y = torch.arange(-(size[1] - 1) / 2, size[1] / 2) / (size[1] - 1)
    else:
        # Even
        y = torch.arange(-size[1] / 2, size[1] / 2) / size[1]
    return torch.meshgrid(x, y)


def estimate_ggd_param(x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
    """Estimate general gaussian distribution.

    Args:
        x (Tensor): shape (b, 1, h, w)
    """
    gamma = torch.arange(0.2, 10 + 0.001, 0.001).to(x)
    r_table = (torch.lgamma(1. / gamma) + torch.lgamma(3. / gamma) -
               2 * torch.lgamma(2. / gamma)).exp()
    r_table = r_table.repeat(x.size(0), 1)

    sigma_sq = x.pow(2).mean(dim=(-1, -2))
    sigma = sigma_sq.sqrt().squeeze(dim=-1)

    assert not torch.isclose(sigma, torch.zeros_like(sigma)).all(), \
        'Expected image with non zero variance of pixel values'

    E = x.abs().mean(dim=(-1, -2))
    rho = sigma_sq / E**2

    indexes = (rho - r_table).abs().argmin(dim=-1)
    solution = gamma[indexes]
    return solution, sigma


def estimate_aggd_param(
        block: torch.Tensor, return_sigma=False) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Estimate AGGD (Asymmetric Generalized Gaussian Distribution) parameters.
    Args:
        block (Tensor): Image block with shape (b, 1, h, w).
    Returns:
        Tensor: alpha, beta_l and beta_r for the AGGD distribution 
        (Estimating the parames in Equation 7 in the paper).
    """
    gam = torch.arange(0.2, 10 + 0.001, 0.001).to(block)
    r_gam = (2 * torch.lgamma(2. / gam) -
             (torch.lgamma(1. / gam) + torch.lgamma(3. / gam))).exp()
    r_gam = r_gam.repeat(block.size(0), 1)

    mask_left = block < 0
    mask_right = block > 0
    count_left = mask_left.sum(dim=(-1, -2), dtype=torch.float32)
    count_right = mask_right.sum(dim=(-1, -2), dtype=torch.float32)

    left_std = safe_sqrt((block * mask_left).pow(2).sum(dim=(-1, -2)) /
                (count_left + EPS))
    right_std = safe_sqrt((block * mask_right).pow(2).sum(dim=(-1, -2)) /
                 (count_right + EPS))

    gammahat = left_std / right_std
    rhat = block.abs().mean(dim=(-1, -2)).pow(2) / block.pow(2).mean(dim=(-1,
                                                                          -2))
    rhatnorm = (rhat * (gammahat.pow(3) + 1) *
                (gammahat + 1)) / (gammahat.pow(2) + 1).pow(2)
    array_position = (r_gam - rhatnorm).abs().argmin(dim=-1)

    alpha = gam[array_position]
    beta_l = left_std.squeeze(-1) * (torch.lgamma(1 / alpha) -
                                     torch.lgamma(3 / alpha)).exp().sqrt()
    beta_r = right_std.squeeze(-1) * (torch.lgamma(1 / alpha) -
                                      torch.lgamma(3 / alpha)).exp().sqrt()

    if return_sigma:
        return alpha, left_std.squeeze(-1), right_std.squeeze(-1)
    else:
        return alpha, beta_l, beta_r


def dct(x, norm=None):
    """
    Discrete Cosine Transform, Type II (a.k.a. the DCT)
    For the meaning of the parameter `norm`, see:
    https://docs.scipy.org/doc/scipy-0.14.0/reference/generated/scipy.fftpack.dct.html
    :param x: the input signal
    :param norm: the normalization, None or 'ortho'
    :return: the DCT-II of the signal over the last dimension
    """
    x_shape = x.shape
    N = x_shape[-1]
    x = x.contiguous().view(-1, N)

    v = torch.cat([x[:, ::2], x[:, 1::2].flip([1])], dim=-1)

    Vc = torch.view_as_real(torch.fft.fft(v, dim=-1))

    k = - torch.arange(N, dtype=x.dtype, device=x.device)[None, :] * np.pi / (2 * N)
    W_r = torch.cos(k)
    W_i = torch.sin(k)

    V = Vc[:, :, 0] * W_r - Vc[:, :, 1] * W_i

    if norm == 'ortho':
        V[:, 0] /= np.sqrt(N) * 2
        V[:, 1:] /= np.sqrt(N / 2) * 2

    V = 2 * V.view(*x_shape)

    return V


def dct2d(x, norm='ortho'):
    """
    2-dimentional Discrete Cosine Transform, Type II (a.k.a. the DCT)
    For the meaning of the parameter `norm`, see:
    https://docs.scipy.org/doc/scipy-0.14.0/reference/generated/scipy.fftpack.dct.html
    :param x: the input signal
    :param norm: the normalization, None or 'ortho'
    :return: the DCT-II of the signal over the last 2 dimensions
    """
    X1 = dct(x, norm=norm)
    X2 = dct(X1.transpose(-1, -2), norm=norm)
    return X2.transpose(-1, -2)
