'''
I think this has something to do with face detection
'''


import cv2
import numpy as np
import os
import mxnet as mx
from skimage import transform as trans
import insightface
import sys
# sys.path.append('/home/jovyan/FaceShifter-2/FaceShifter3/')
from insightface_func.face_detect_crop_single import Face_detect_crop
import kornia


M = np.array([[ 0.57142857, 0., 32.],[ 0.,0.57142857, 32.]]) ##??
IM = np.array([[[1.75, -0., -56.],[ -0., 1.75, -56.]]])  ##??


def square_crop(im, S):  ##im = img
    if im.shape[0] > im.shape[1]: ##height가 더 크면
        height = S    ##S를 height로 바꾸라 
        width = int(float(im.shape[1]) / im.shape[0] * S)  ##new width = original width / S * height 즉, S만큼 height에 더 주고, widgh에서 제외하라는것 
        scale = float(S) / im.shape[0]
    else:  ##아니면 height를 S예 비례하게 작게하고 width를 크게하라 
        width = S
        height = int(float(im.shape[0]) / im.shape[1] * S)
        scale = float(S) / im.shape[1]
    resized_im = cv2.resize(im, (width, height))  ##새로운 사이즈로 다시 리사이즈 한다 
    det_im = np.zeros((S, S, 3), dtype=np.uint8)   ## detected img를 0값으로 만든다
    det_im[:resized_im.shape[0], :resized_im.shape[1], :] = resized_im   ##det_im에 detecting part를 껴넣는다
    return det_im, scale


def transform(data, center, output_size, scale, rotation): ##what is the value of center? -> (bbox[2] + bbox[0]) / 2, (bbox[3] + bbox[1]) / 2 즉, 센터는 픽셀의 위치 index
    scale_ratio = scale
    rot = float(rotation) * np.pi / 180.0 ##각도 로테이션 주는 것 
    #translation = (output_size/2-center[0]*scale_ratio, output_size/2-center[1]*scale_ratio)
    t1 = trans.SimilarityTransform(scale=scale_ratio)
    cx = center[0] * scale_ratio
    cy = center[1] * scale_ratio
    t2 = trans.SimilarityTransform(translation=(-1 * cx, -1 * cy))
    t3 = trans.SimilarityTransform(rotation=rot)
    t4 = trans.SimilarityTransform(translation=(output_size / 2,
                                                output_size / 2))
    t = t1 + t2 + t3 + t4
    M = t.params[0:2]
    cropped = cv2.warpAffine(data,  ##data를 M 매트리스 만큼 transformation을 줘라라는 뜻 
                             M, (output_size, output_size),
                             borderValue=0.0)
    return cropped, M


def trans_points2d_batch(pts, M):
    new_pts = np.zeros(shape=pts.shape, dtype=np.float32)  ##pts = model prediction 결과물
    for j in range(pts.shape[0]):  ##shape[0] = batch_size?  shape[1] = output len?
        for i in range(pts.shape[1]):
            pt = pts[j][i]
            new_pt = np.array([pt[0], pt[1], 1.], dtype=np.float32)
            new_pt = np.dot(M[j], new_pt)
            new_pts[j][i] = new_pt[0:2]
    return new_pts


def trans_points2d(pts, M):
    new_pts = np.zeros(shape=pts.shape, dtype=np.float32)
    for i in range(pts.shape[0]):
        pt = pts[i]
        new_pt = np.array([pt[0], pt[1], 1.], dtype=np.float32)
        new_pt = np.dot(M, new_pt)
        #print('new_pt', new_pt.shape, new_pt)
        new_pts[i] = new_pt[0:2]

    return new_pts


def trans_points3d(pts, M):
    scale = np.sqrt(M[0][0] * M[0][0] + M[0][1] * M[0][1])
    #print(scale)
    new_pts = np.zeros(shape=pts.shape, dtype=np.float32)
    for i in range(pts.shape[0]):
        pt = pts[i]
        new_pt = np.array([pt[0], pt[1], 1.], dtype=np.float32)
        new_pt = np.dot(M, new_pt)
        #print('new_pt', new_pt.shape, new_pt)
        new_pts[i][0:2] = new_pt[0:2]
        new_pts[i][2] = pts[i][2] * scale

    return new_pts


def trans_points(pts, M):
    if pts.shape[1] == 2: ##2개의 값을 가지고있으면 2D이고 3개이면 3D일것이다 
        return trans_points2d(pts, M)
    else:
        return trans_points3d(pts, M)


class Handler:
    def __init__(self, prefix, epoch, im_size=192, det_size=224, ctx_id=0, root='./insightface_func/models'):
        print('loading', prefix, epoch)
        if ctx_id >= 0:
            ctx = mx.gpu(ctx_id)  ##ctx_id = GPU 넘버를 말하는 것??
        else:
            ctx = mx.cpu()
        image_size = (im_size, im_size)
#         self.detector = insightface.model_zoo.get_model(
#             'retinaface_mnet025_v2')  #can replace with your own face detector
        self.detector = Face_detect_crop(name='antelope', root=root)  ##face 인식한 후 그 부분만 crop 하는 모델 
        self.detector.prepare(ctx_id=ctx_id, det_thresh=0.6, det_size=(640,640))
        #self.detector = insightface.model_zoo.get_model('retinaface_r50_v1')
        #self.detector.prepare(ctx_id=ctx_id)
        self.det_size = det_size
        sym, arg_params, aux_params = mx.model.load_checkpoint(prefix, epoch)  ##pre-trained 모델 가져오기 
        all_layers = sym.get_internals()
        sym = all_layers['fc1_output']  ##fc1_output만 가져와라
        self.image_size = image_size
        model = mx.mod.Module(symbol=sym, context=ctx, label_names=None)  ##모듈중에 fc1_output 레이어 값만 가져와라 
        model.bind(for_training=False,
                   data_shapes=[('data', (1, 3, image_size[0], image_size[1]))  ## (batch_size, 3 cheannels, height, width)
                                ])
        model.set_params(arg_params, aux_params)
        self.model = model
        self.image_size = image_size
    
    
    def get_without_detection_batch(self, img, M, IM):
        rimg = kornia.warp_affine(img, M.repeat(img.shape[0],1,1), (192, 192), padding_mode='zeros')  ##M.repeat = (channel, 1, 1) | (192, 192) = dsize – size of the output image (height, width).
        ##rimg  = (B,C,D,H,W)
        rimg = kornia.bgr_to_rgb(rimg) ## result rimg = (batchsize, 3, H,W)
        
        data = mx.nd.array(rimg)
        db = mx.io.DataBatch(data=(data, ))
        self.model.forward(db, is_train=False)
        pred = self.model.get_outputs()[-1].asnumpy()
        pred = pred.reshape((pred.shape[0], -1, 2))  
        pred[:, :, 0:2] += 1
        pred[:, :, 0:2] *= (self.image_size[0] // 2)
        
        pred = trans_points2d_batch(pred, IM.repeat(img.shape[0],1,1).numpy())
        
        return pred
    
    
    def get_without_detection_without_transform(self, img):
        input_blob = np.zeros((1, 3) + self.image_size, dtype=np.float32)
        rimg = cv2.warpAffine(img, M, self.image_size, borderValue=0.0)
        rimg = cv2.cvtColor(rimg, cv2.COLOR_BGR2RGB)
        rimg = np.transpose(rimg, (2, 0, 1))  #3*112*112, RGB
        
        input_blob[0] = rimg
        data = mx.nd.array(input_blob)
        db = mx.io.DataBatch(data=(data, ))
        self.model.forward(db, is_train=False)
        pred = self.model.get_outputs()[-1].asnumpy()[0]
        pred = pred.reshape((-1, 2))
        pred[:, 0:2] += 1
        pred[:, 0:2] *= (self.image_size[0] // 2)
        pred = trans_points2d(pred, IM)
        
        return pred
    
    
    def get_without_detection(self, img):
        bbox = [0, 0, img.shape[0], img.shape[1]]  ##img.shape[0] = height?, img.shape[1] = width
        input_blob = np.zeros((1, 3) + self.image_size, dtype=np.float32)  ##1 for batch, 3 for channel, self.image_size = H, W
        
        w, h = (bbox[2] - bbox[0]), (bbox[3] - bbox[1])
        center = (bbox[2] + bbox[0]) / 2, (bbox[3] + bbox[1]) / 2
        rotate = 0
        _scale = self.image_size[0] * 2 / 3.0 / max(w, h)
        
        rimg, M = transform(img, center, self.image_size[0], _scale,
                            rotate)
        rimg = cv2.cvtColor(rimg, cv2.COLOR_BGR2RGB)
        rimg = np.transpose(rimg, (2, 0, 1))  #3*112*112, RGB
        
        input_blob[0] = rimg
        data = mx.nd.array(input_blob)
        db = mx.io.DataBatch(data=(data, ))
        self.model.forward(db, is_train=False)
        pred = self.model.get_outputs()[-1].asnumpy()[0]
        if pred.shape[0] >= 3000:
            pred = pred.reshape((-1, 3))
        else:
            pred = pred.reshape((-1, 2))
        pred[:, 0:2] += 1
        pred[:, 0:2] *= (self.image_size[0] // 2)
        if pred.shape[1] == 3:
            pred[:, 2] *= (self.image_size[0] // 2)

        IM = cv2.invertAffineTransform(M)
        pred = trans_points(pred, IM)
        
        return pred
    
    
    def get(self, img, get_all=False):
        out = []
        det_im, det_scale = square_crop(img, self.det_size)
        bboxes, _ = self.detector.detect(det_im)
        if bboxes.shape[0] == 0:
            return out
        bboxes /= det_scale
        if not get_all:
            areas = []
            for i in range(bboxes.shape[0]):
                x = bboxes[i]
                area = (x[2] - x[0]) * (x[3] - x[1])
                areas.append(area)
            m = np.argsort(areas)[-1]
            bboxes = bboxes[m:m + 1]
        for i in range(bboxes.shape[0]):
            bbox = bboxes[i]
            input_blob = np.zeros((1, 3) + self.image_size, dtype=np.float32)
            w, h = (bbox[2] - bbox[0]), (bbox[3] - bbox[1])
            center = (bbox[2] + bbox[0]) / 2, (bbox[3] + bbox[1]) / 2
            rotate = 0
            _scale = self.image_size[0] * 2 / 3.0 / max(w, h)
            rimg, M = transform(img, center, self.image_size[0], _scale,
                                rotate)
            rimg = cv2.cvtColor(rimg, cv2.COLOR_BGR2RGB)
            rimg = np.transpose(rimg, (2, 0, 1))  #3*112*112, RGB
            input_blob[0] = rimg
            data = mx.nd.array(input_blob)
            db = mx.io.DataBatch(data=(data, ))
            self.model.forward(db, is_train=False)
            pred = self.model.get_outputs()[-1].asnumpy()[0]
            if pred.shape[0] >= 3000:
                pred = pred.reshape((-1, 3))
            else:
                pred = pred.reshape((-1, 2))
            pred[:, 0:2] += 1
            pred[:, 0:2] *= (self.image_size[0] // 2)
            if pred.shape[1] == 3:
                pred[:, 2] *= (self.image_size[0] // 2)

            IM = cv2.invertAffineTransform(M)
            pred = trans_points(pred, IM)
            out.append(pred)
        return out
