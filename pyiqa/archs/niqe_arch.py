r"""NIQE and ILNIQE Metrics
NIQE Metric
    Created by: https://github.com/xinntao/BasicSR/blob/5668ba75eb8a77e8d2dd46746a36fee0fbb0fdcd/basicsr/metrics/niqe.py
    Modified by: Jiadi Mo (https://github.com/JiadiMo)
    Reference:
        MATLAB codes: http://live.ece.utexas.edu/research/quality/niqe_release.zip

ILNIQE Metric
    Created by: Chaofeng Chen (https://github.com/chaofengc)
    Reference:
        - Python codes: https://github.com/IceClear/IL-NIQE/blob/master/IL-NIQE.py
        - Matlab codes: https://www4.comp.polyu.edu.hk/~cslzhang/IQA/ILNIQE/Files/ILNIQE.zip
"""

import math
import numpy as np
import scipy
import scipy.io
import torch
import torch.nn.functional as F

from pyiqa.utils.color_util import to_y_channel
from pyiqa.utils.download_util import load_file_from_url
from pyiqa.utils.matlab_functions import imresize, fspecial_gauss
from .func_util import estimate_aggd_param, torch_cov, normalize_img_with_guass, nanmean, imfilter
from .arch_util import SimpleSamePadding2d, SymmetricPad2d
from pyiqa.archs.fsim_arch import _construct_filters
from pyiqa.utils.registry import ARCH_REGISTRY


default_model_urls = {
    'url': 'https://github.com/chaofengc/IQA-PyTorch/releases/download/v0.1-weights/niqe_modelparameters.mat',
    'niqe': 'https://github.com/chaofengc/IQA-PyTorch/releases/download/v0.1-weights/niqe_modelparameters.mat',
    'ilniqe': 'https://github.com/chaofengc/IQA-PyTorch/releases/download/v0.1-weights/ILNIQE_templateModel.mat',
}


def fitweibull(x, iters=50, eps=1e-2):
    """
    ref: https://github.com/mlosch/python-weibullfit/blob/master/weibull/backend_pytorch.py

    Fits a 2-parameter Weibull distribution to the given data using maximum-likelihood estimation.
    :param x (tensor): (B, N), batch of samples from an (unknown) distribution. Each value must satisfy x > 0.
    :param iters: Maximum number of iterations
    :param eps: Stopping criterion. Fit is stopped ff the change within two iterations is smaller than eps.
    :param use_cuda: Use gpu
    :return: Tuple (Shape, Scale) which can be (NaN, NaN) if a fit is impossible.
        Impossible fits may be due to 0-values in x.
    """
    ln_x = torch.log(x)
    k = 1.2 / torch.std(ln_x, dim=1, keepdim=True)
    k_t_1 = k

    for t in range(iters):
        # Partial derivative df/dk
        x_k = x ** k.repeat(1, x.shape[1])
        x_k_ln_x = x_k * ln_x
        ff = torch.sum(x_k_ln_x, dim=-1, keepdim=True)
        fg = torch.sum(x_k, dim=-1, keepdim=True)
        f1 = torch.mean(ln_x, dim=-1, keepdim=True)
        f = ff/fg - f1 - (1.0 / k)

        ff_prime = torch.sum(x_k_ln_x * ln_x, dim=-1, keepdim=True)
        fg_prime = ff
        f_prime = (ff_prime / fg - (ff / fg * fg_prime / fg)) + (1. / (k * k))

        # Newton-Raphson method k = k - f(k;x)/f'(k;x)
        k = k - f / f_prime
        error = torch.abs(k - k_t_1).max().item()
        if error < eps:
            break
        k_t_1 = k

    # Lambda (scale) can be calculated directly
    lam = torch.mean(x ** k.repeat(1, x.shape[1]), dim=-1, keepdim=True) ** (1.0 / k)

    return k, lam  # Shape (SC), Scale (FE)


def compute_feature(block: torch.Tensor,
                    ilniqe: bool = False,
                ) -> torch.Tensor:
    """Compute features.
    Args:
        block (Tensor): Image block in shape (b, c, h, w).
    Returns:
        list: Features with length of 18.
    """
    bsz = block.shape[0]
    aggd_block = block[:, [0]]
    alpha, beta_l, beta_r = estimate_aggd_param(aggd_block)
    feat = [alpha, (beta_l + beta_r) / 2]

    # distortions disturb the fairly regular structure of natural images.
    # This deviation can be captured by analyzing the sample distribution of
    # the products of pairs of adjacent coefficients computed along
    # horizontal, vertical and diagonal orientations.
    shifts = [[0, 1], [1, 0], [1, 1], [1, -1]]
    for i in range(len(shifts)):
        shifted_block = torch.roll(aggd_block, shifts[i], dims=(2, 3))
        alpha, beta_l, beta_r = estimate_aggd_param(aggd_block * shifted_block)
        # Eq. 8
        mean = (beta_r - beta_l) * (torch.lgamma(2 / alpha) -
                                    torch.lgamma(1 / alpha)).exp()
        feat.extend((alpha, mean, beta_l, beta_r))
    feat = [x.reshape(bsz, 1) for x in feat]

    if ilniqe:
        tmp_block = block[:, 1:4]
        channels = 4 - 1
        shape, scale = fitweibull(tmp_block.reshape(bsz * channels, -1))
        scale_shape = torch.stack((scale.reshape(bsz, channels), shape.reshape(bsz, channels)), dim=-1).reshape(bsz, -1)
        feat.append(scale_shape)

        mu = torch.mean(block[:, 4:7], dim=(2,3))
        sigmaSquare = torch.var(block[:, 4:7], dim=(2,3))
        mu_sigma = torch.stack((mu, sigmaSquare), dim=-1).reshape(bsz, -1)
        feat.append(mu_sigma)

        channels = 85 - 7
        tmp_block = block[:, 7:85].reshape(bsz*channels, 1, *block.shape[2:])
        alpha_data, beta_l_data, beta_r_data = estimate_aggd_param(tmp_block)
        alpha_data = alpha_data.reshape(bsz, channels)
        beta_l_data = beta_l_data.reshape(bsz, channels)
        beta_r_data = beta_r_data.reshape(bsz, channels)
        alpha_beta = torch.stack([alpha_data, (beta_l_data + beta_r_data) / 2], dim=-1).reshape(bsz, -1)
        feat.append(alpha_beta)

        tmp_block = block[:, 85:109]
        channels = 109 - 85
        shape, scale = fitweibull(tmp_block.reshape(bsz * channels, -1))
        scale_shape = torch.stack((scale.reshape(bsz, channels), shape.reshape(bsz, channels)), dim=-1).reshape(bsz, -1)
        feat.append(scale_shape)
    
    feat = torch.cat(feat, dim=-1)
    return feat 


def niqe(img: torch.Tensor,
         mu_pris_param: torch.Tensor,
         cov_pris_param: torch.Tensor,
         block_size_h: int = 96,
         block_size_w: int = 96) -> torch.Tensor:
    """Calculate NIQE (Natural Image Quality Evaluator) metric.
    Args:
        img (Tensor): Input image.
        mu_pris_param (Tensor): Mean of a pre-defined multivariate Gaussian
            model calculated on the pristine dataset.
        cov_pris_param (Tensor): Covariance of a pre-defined multivariate
            Gaussian model calculated on the pristine dataset.
        gaussian_window (Tensor): A 7x7 Gaussian window used for smoothing the image.
        block_size_h (int): Height of the blocks in to which image is divided.
            Default: 96 (the official recommended value).
        block_size_w (int): Width of the blocks in to which image is divided.
            Default: 96 (the official recommended value).
    """
    assert img.ndim == 4, (
        'Input image must be a gray or Y (of YCbCr) image with shape (b, c, h, w).'
    )
    # crop image
    b, c, h, w = img.shape
    num_block_h = math.floor(h / block_size_h)
    num_block_w = math.floor(w / block_size_w)
    img = img[..., 0:num_block_h * block_size_h, 0:num_block_w * block_size_w]

    distparam = []  # dist param is actually the multiscale features
    for scale in (1, 2):  # perform on two scales (1, 2)
        img_normalized = normalize_img_with_guass(img, padding='replicate')

        feat = []
        for idx_w in range(num_block_w):
            for idx_h in range(num_block_h):
                # process ecah block
                block = img_normalized[..., idx_h * block_size_h //
                                      scale:(idx_h + 1) * block_size_h //
                                      scale, idx_w * block_size_w //
                                      scale:(idx_w + 1) * block_size_w //
                                      scale]
                feat.append(compute_feature(block))

        distparam.append(torch.stack(feat).transpose(0, 1))

        if scale == 1:
            img = imresize(img / 255., scale=0.5, antialiasing=True)
            img = img * 255.

    distparam = torch.cat(distparam, -1)

    # fit a MVG (multivariate Gaussian) model to distorted patch features
    mu_distparam = nanmean(distparam, dim=1) 

    distparam_no_nan = torch.nan_to_num(distparam) 
    cov_distparam = torch_cov(distparam_no_nan.transpose(1, 2))

    # compute niqe quality, Eq. 10 in the paper
    invcov_param = torch.linalg.pinv(
        (cov_pris_param + cov_distparam) / 2)
    diff = (mu_pris_param - mu_distparam).unsqueeze(1)
    quality = torch.bmm(torch.bmm(diff, invcov_param),
                        diff.transpose(1, 2)).squeeze()

    quality = torch.sqrt(quality)
    return quality


def calculate_niqe(img: torch.Tensor,
                   crop_border: int = 0,
                   test_y_channel: bool = True,
                   pretrained_model_path: str = None,
                   color_space: str = 'yiq',
                   **kwargs) -> torch.Tensor:
    """Calculate NIQE (Natural Image Quality Evaluator) metric.
    Args:
        img (Tensor): Input image whose quality needs to be computed.
        crop_border (int): Cropped pixels in each edge of an image. These
            pixels are not involved in the metric calculation.
        test_y_channel (Bool): Whether converted to 'y' (of MATLAB YCbCr) or 'gray'.
        pretrained_model_path (str): The pretrained model path.
    Returns:
        Tensor: NIQE result.
    """

    params = scipy.io.loadmat(pretrained_model_path)
    mu_pris_param = np.ravel(params['mu_prisparam'])
    cov_pris_param = params['cov_prisparam']
    mu_pris_param = torch.from_numpy(mu_pris_param).to(img)
    cov_pris_param = torch.from_numpy(cov_pris_param).to(img)

    mu_pris_param = mu_pris_param.repeat(img.size(0), 1)
    cov_pris_param = cov_pris_param.repeat(img.size(0), 1, 1)

    if test_y_channel and img.shape[1] == 3:
        img = to_y_channel(img, 255, color_space)

    if crop_border != 0:
        img = img[..., crop_border:-crop_border, crop_border:-crop_border]

    niqe_result = niqe(img, mu_pris_param, cov_pris_param)

    return niqe_result


def gauDerivative(sigma, in_ch=1, out_ch=1, device=None):
    halfLength = math.ceil(3 * sigma)

    x, y = np.meshgrid(
        np.linspace(-halfLength, halfLength, 2 * halfLength + 1),
        np.linspace(-halfLength, halfLength, 2 * halfLength + 1))

    gauDerX = x * np.exp(-(x**2 + y**2) / 2 / sigma / sigma)
    gauDerY = y * np.exp(-(x**2 + y**2) / 2 / sigma / sigma)

    dx = torch.from_numpy(gauDerX).to(device)
    dy = torch.from_numpy(gauDerY).to(device)
    dx = dx.repeat(out_ch, in_ch, 1, 1)
    dy = dy.repeat(out_ch, in_ch, 1, 1)

    return dx, dy 


def conv2d(input, weight, bias=None, stride=1, padding='same', dilation=1, groups=1):
    """matlab like conv2d, weights needs to be reversed 
    """
    kernel_size = weight.shape[-1]
    if padding.lower() == 'same':
        pad_func = SimpleSamePadding2d(kernel_size, stride=1, mode='constant')
    elif padding.lower() == 'replicate':
        pad_func = SimpleSamePadding2d(kernel_size, stride=1, mode='replicate')
    elif padding.lower() == 'symmetric':
        pad_func = SymmetricPad2d(kernel_size//2)
    
    weight = torch.flip(weight, dims=(-1, -2)) 
    return F.conv2d(
        pad_func(input), weight, bias, stride, dilation=dilation, groups=groups)


def ilniqe(img: torch.Tensor,
           mu_pris_param: torch.Tensor,
           cov_pris_param: torch.Tensor,
           principleVectors: torch.Tensor,
           meanOfSampleData: torch.Tensor,
           resize: bool = True,
           block_size_h: int = 84,
           block_size_w: int = 84) -> torch.Tensor:
    """Calculate IL-NIQE (Integrated Local Natural Image Quality Evaluator) metric.
    Args:
        img (Tensor): Input image.
        mu_pris_param (Tensor): Mean of a pre-defined multivariate Gaussian
            model calculated on the pristine dataset.
        cov_pris_param (Tensor): Covariance of a pre-defined multivariate
            Gaussian model calculated on the pristine dataset.
        principleVectors (Tensor): Features from official .mat file.
        meanOfSampleData (Tensor): Features from official .mat file.
        resize (Bloolean): resize image. Default: True.
        block_size_h (int): Height of the blocks in to which image is divided.
            Default: 84 (the official recommended value).
        block_size_w (int): Width of the blocks in to which image is divided.
            Default: 84 (the official recommended value).
    """
    assert img.ndim == 4, ('Input image must be a gray or Y (of YCbCr) image with shape (b, c, h, w).')

    sigmaForGauDerivative = 1.66
    KforLog = 0.00001
    normalizedWidth = 524
    minWaveLength = 2.4
    sigmaOnf = 0.55
    mult = 1.31
    dThetaOnSigma = 1.10
    scaleFactorForLoG = 0.87
    scaleFactorForGaussianDer = 0.28
    sigmaForDownsample = 0.9
    
    EPS = 1e-8
    scales = 3
    orientations = 4
    infConst = 10000
    nanConst = 2000

    if resize:
        img = imresize(img, sizes=(normalizedWidth, normalizedWidth))
        img = img.clamp(0.0, 255.0)

    # crop image
    b, c, h, w = img.shape
    num_block_h = math.floor(h / block_size_h)
    num_block_w = math.floor(w / block_size_w)
    img = img[..., 0:num_block_h * block_size_h, 0:num_block_w * block_size_w]
    ospace_weight = torch.tensor([
        [0.3, 0.04, -0.35],
        [0.34, -0.6, 0.17],
        [0.06, 0.63, 0.27],
    ]).to(img)

    O_img = img.permute(0, 2, 3, 1) @ ospace_weight.T
    O_img = O_img.permute(0, 3, 1, 2)

    distparam = []  # dist param is actually the multiscale features
    for scale in (1, 2):  # perform on two scales (1, 2)
        struct_dis = normalize_img_with_guass(O_img[:, [2]], kernel_size=5, sigma=5. / 6, padding='replicate')

        dx, dy = gauDerivative(sigmaForGauDerivative / (scale**scaleFactorForGaussianDer), device=img)

        Ix = conv2d(O_img, dx.repeat(3, 1, 1, 1), groups=3)
        Iy = conv2d(O_img, dy.repeat(3, 1, 1, 1), groups=3) 
        GM = torch.sqrt(Ix ** 2 + Iy ** 2 + EPS)
        Ixy = torch.stack((Ix, Iy), dim=2).reshape(
            Ix.shape[0], Ix.shape[1]*2, *Ix.shape[2:]
        ) # reshape to (IxO1, IxO1, IxO2, IyO2, IxO3, IyO3)
        
        logRGB = torch.log(img + KforLog)
        logRGBMS = logRGB - logRGB.mean(dim=(2, 3), keepdim=True)

        Intensity = logRGBMS.sum(dim=1, keepdim=True) / np.sqrt(3)
        BY = (logRGBMS[:, [0]] + logRGBMS[:, [1]] - 2 * logRGBMS[:, [2]]) / np.sqrt(6)
        RG = (logRGBMS[:, [0]] - logRGBMS[:, [1]]) / np.sqrt(2) 

        compositeMat = torch.cat(
            [struct_dis, GM, Intensity, BY, RG, Ixy], dim=1
        ) 

        O3 = O_img[:, [2]]
        # gabor filter in shape (b, ori * scale, h, w)
        LGFilters = _construct_filters(
            O3, 
            scales=scales,
            orientations=orientations,
            min_length=minWaveLength / (scale**scaleFactorForLoG),
            sigma_f=sigmaOnf,
            mult=mult,
            delta_theta=dThetaOnSigma,
            use_lowpass_filter=False)
        # reformat to scale * ori
        b, _, h, w = LGFilters.shape
        LGFilters = LGFilters.reshape(b, orientations, scales, h, w).transpose(1, 2).reshape(b, -1, h, w)
        # TODO: current filters needs to be transposed to get same results as matlab, find the bug 
        LGFilters = LGFilters.transpose(-1, -2)
        fftIm = torch.fft.fft2(O3)

        logResponse = []
        partialDer = []
        GM = []
        for index in range(LGFilters.shape[1]):
            filter = LGFilters[:, [index]]
            response = torch.fft.ifft2(filter * fftIm)
            realRes = torch.real(response)
            imagRes = torch.imag(response)

            partialXReal = conv2d(realRes, dx)
            partialYReal = conv2d(realRes, dy)
            realGM = torch.sqrt(partialXReal**2 + partialYReal**2 + EPS)

            partialXImag = conv2d(imagRes, dx)
            partialYImag = conv2d(imagRes, dy)
            imagGM = torch.sqrt(partialXImag**2 + partialYImag**2 + EPS)

            logResponse.append(realRes)
            logResponse.append(imagRes)
            partialDer.append(partialXReal)
            partialDer.append(partialYReal)
            partialDer.append(partialXImag)
            partialDer.append(partialYImag)
            GM.append(realGM)
            GM.append(imagGM)
        logResponse = torch.cat(logResponse, dim=1)
        partialDer = torch.cat(partialDer, dim=1)
        GM = torch.cat(GM, dim=1)
        compositeMat = torch.cat((compositeMat, logResponse, partialDer, GM), dim=1)

        feat = []
        for idx_w in range(num_block_w):
            for idx_h in range(num_block_h):
                block_pos = [
                    idx_h * block_size_h // scale, (idx_h + 1) * block_size_h // scale, idx_w * block_size_w // scale,
                    (idx_w + 1) * block_size_w // scale
                ]
                block = compositeMat[..., block_pos[0]:block_pos[1], block_pos[2]:block_pos[3]]
                feat.append(compute_feature(block, ilniqe=True))

        distparam.append(torch.stack(feat, dim=1))

        gauForDS = fspecial_gauss(math.ceil(6 * sigmaForDownsample), sigmaForDownsample).to(img)
        filterResult = imfilter(O_img, gauForDS.repeat(3, 1, 1, 1), padding='replicate', groups=3)
        O_img = filterResult[..., ::2, ::2]
        filterResult = imfilter(img, gauForDS.repeat(3, 1, 1, 1), padding='replicate', groups=3)
        img = filterResult[..., ::2, ::2]

    distparam = torch.cat(distparam, dim=-1) # b, block_num, feature_num 
    distparam[distparam > infConst] = infConst

    # fit a MVG (multivariate Gaussian) model to distorted patch features
    coefficientsViaPCA = torch.bmm(principleVectors.transpose(1, 2), (distparam - meanOfSampleData.unsqueeze(1)).transpose(1, 2))
    final_features = coefficientsViaPCA.transpose(1, 2)
    b, blk_num, feat_num = final_features.shape

    # remove block features with nan and compute nonan cov
    nan_mask = torch.isnan(final_features).any(dim=2, keepdim=True)
    final_features_nonan = final_features.masked_select(~nan_mask).reshape(b, -1, feat_num)
    cov_distparam = torch_cov(final_features_nonan, rowvar=False)

    # replace nan in final features with mu
    mu_final_features = nanmean(final_features, dim=1, keepdim=True) 
    final_features_withmu = torch.where(torch.isnan(final_features), mu_final_features, final_features) 

    # compute ilniqe quality
    invcov_param = torch.linalg.pinv((cov_pris_param + cov_distparam) / 2)
    diff = final_features_withmu - mu_pris_param.unsqueeze(1)
    quality = (torch.bmm(diff, invcov_param) * diff).sum(dim=-1)
    quality = torch.sqrt(quality).mean(dim=1)

    return quality


def calculate_ilniqe(img: torch.Tensor,
                     crop_border: int = 0,
                     pretrained_model_path: str = None,
                     **kwargs) -> torch.Tensor:
    """Calculate IL-NIQE metric.
    Args:
        img (Tensor): Input image whose quality needs to be computed.
        crop_border (int): Cropped pixels in each edge of an image. These
            pixels are not involved in the metric calculation.
        pretrained_model_path (str): The pretrained model path.
    Returns:
        Tensor: IL-NIQE result.
    """

    params = scipy.io.loadmat(pretrained_model_path)
    img = img * 255.
    img = img.to(torch.float64)

    mu_pris_param = np.ravel(params['templateModel'][0][0])
    cov_pris_param = params['templateModel'][0][1]
    meanOfSampleData = np.ravel(params['templateModel'][0][2])
    principleVectors = params['templateModel'][0][3]

    mu_pris_param = torch.from_numpy(mu_pris_param).to(img)
    cov_pris_param = torch.from_numpy(cov_pris_param).to(img)
    meanOfSampleData = torch.from_numpy(meanOfSampleData).to(img)
    principleVectors = torch.from_numpy(principleVectors).to(img)

    mu_pris_param = mu_pris_param.repeat(img.size(0), 1)
    cov_pris_param = cov_pris_param.repeat(img.size(0), 1, 1)
    meanOfSampleData = meanOfSampleData.repeat(img.size(0), 1)
    principleVectors = principleVectors.repeat(img.size(0), 1, 1)

    if crop_border != 0:
        img = img[..., crop_border:-crop_border, crop_border:-crop_border]

    ilniqe_result = ilniqe(img, mu_pris_param, cov_pris_param, principleVectors, meanOfSampleData)

    return ilniqe_result


@ARCH_REGISTRY.register()
class NIQE(torch.nn.Module):
    r"""Args:
        channels (int): Number of processed channel.
        test_y_channel (bool): whether to use y channel on ycbcr.
        crop_border (int): Cropped pixels in each edge of an image. These
            pixels are not involved in the metric calculation.
        pretrained_model_path (str): The pretrained model path.
    References:
        Mittal, Anish, Rajiv Soundararajan, and Alan C. Bovik. 
        "Making a “completely blind” image quality analyzer." 
        IEEE Signal Processing Letters (SPL) 20.3 (2012): 209-212.
    """

    def __init__(self,
                 channels: int = 1,
                 test_y_channel: bool = True,
                 color_space: str = 'yiq',
                 crop_border: int = 0,
                 pretrained_model_path: str = None) -> None:

        super(NIQE, self).__init__()
        self.channels = channels
        self.test_y_channel = test_y_channel
        self.color_space = color_space
        self.crop_border = crop_border
        if pretrained_model_path is not None:
            self.pretrained_model_path = pretrained_model_path
        else:
            self.pretrained_model_path = load_file_from_url(default_model_urls['url'])

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        r"""Computation of NIQE metric.
        Args:
            X: An input tensor. Shape :math:`(N, C, H, W)`.
        Returns:
            Value of niqe metric in [0, 1] range.
        """
        score = calculate_niqe(X, self.crop_border, self.test_y_channel,
                               self.pretrained_model_path, self.color_space)
        return score


@ARCH_REGISTRY.register()
class ILNIQE(torch.nn.Module):
    r"""Args:
        channels (int): Number of processed channel.
        test_y_channel (bool): whether to use y channel on ycbcr.
        crop_border (int): Cropped pixels in each edge of an image. These
            pixels are not involved in the metric calculation.
        pretrained_model_path (str): The pretrained model path.
    References:
        Zhang, Lin, Lei Zhang, and Alan C. Bovik. "A feature-enriched 
        completely blind image quality evaluator." IEEE Transactions 
        on Image Processing 24.8 (2015): 2579-2591.
    """

    def __init__(self, channels: int = 3, crop_border: int = 0, pretrained_model_path: str = None) -> None:

        super(ILNIQE, self).__init__()
        self.channels = channels
        self.crop_border = crop_border
        if pretrained_model_path is not None:
            self.pretrained_model_path = pretrained_model_path
        else:
            self.pretrained_model_path = load_file_from_url(default_model_urls['ilniqe'])

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        r"""Computation of NIQE metric.
        Args:
            X: An input tensor. Shape :math:`(N, C, H, W)`.
        Returns:
            Value of niqe metric in [0, 1] range.
        """
        score = calculate_ilniqe(X, self.crop_border, self.pretrained_model_path)
        return score
